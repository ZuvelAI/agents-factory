from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.backend.tests.usage_support import NOW, event, price
from agents_factory.modules.usage.models import (
    CommercialPolicy,
    Measurements,
    Money,
    TechnicalLimits,
    UsageConfiguration,
    UsageEvent,
)
from agents_factory.modules.usage.pricing import quote_usage
from agents_factory.modules.usage.guardrails import (
    TechnicalCounters,
    UsageTotals,
    check_hard_limits,
    commercial_signals,
)


def test_price_versions_missing_usage_subsets_and_provider_currency():
    card, sample = price(), event()
    quote, _ = quote_usage(sample, (card,))
    assert quote.amount == Decimal("0.000370000000")
    assert quote_usage(sample, ())[0].amount is None
    unknown = sample.model_copy(
        update={"measurements": Measurements(input_tokens=100, output_tokens=50)}
    )
    assert quote_usage(unknown, (card,))[0].reason == "measurement_unavailable"
    next_card = card.model_copy(
        update={"id": uuid4(), "effective_from": NOW + timedelta(days=1)}
    )
    assert quote_usage(sample, (card, next_card))[0].price_version == card.id
    assert (
        quote_usage(
            sample.model_copy(update={"occurred_at": next_card.effective_from}),
            (card, next_card),
        )[0].price_version
        == next_card.id
    )
    ended = card.model_copy(update={"effective_until": NOW + timedelta(days=1)})
    assert (
        quote_usage(
            sample.model_copy(update={"occurred_at": ended.effective_until}), (ended,)
        )[0].reason
        == "price_unavailable"
    )
    for kind in ("whatsapp", "tool", "storage", "infrastructure"):
        measured = UsageEvent(
            source_key=kind,
            occurred_at=NOW,
            kind=kind,
            provider="fixture",
            product="meter",
            currency="EUR",
            measurements=Measurements(),
            provider_cost=Money(amount=Decimal("0.123456789012"), currency="EUR"),
        )
        assert quote_usage(measured, ())[0].amount == measured.provider_cost.amount
    with pytest.raises(ValidationError):
        Measurements(input_tokens=1, cached_input_tokens=2)
    with pytest.raises(ValidationError):
        Money(amount=Decimal("NaN"), currency="USD")
    with pytest.raises(ValidationError):
        UsageConfiguration(prices=(card, card))


def test_commercial_grace_does_not_disable_independent_hard_limits():
    policy = CommercialPolicy(
        messages=100,
        conversations=100,
        model_tokens=100,
        storage_bytes=100,
        concurrent_runs=100,
        tool_calls=100,
        cost=Money(amount=Decimal(100), currency="USD"),
    )
    for amount, state in (
        (69, "within_budget"),
        (70, "alert"),
        (85, "alert"),
        (100, "grace_overage"),
        (120, "grace_overage"),
    ):
        totals = UsageTotals(
            messages=amount,
            conversations=amount,
            model_tokens=amount,
            storage_bytes=amount,
            concurrent_runs=amount,
            tool_calls=amount,
            cost=Money(amount=Decimal(amount), currency="USD"),
        )
        assert {signal.state for signal in commercial_signals(policy, totals)} == {
            state
        }
    assert {s.state for s in commercial_signals(policy, UsageTotals())} == {"unknown"}
    limits = TechnicalLimits()
    permitted = []
    for proposed in range(1, 100):
        if not check_hard_limits(
            limits, TechnicalCounters(tool_calls=proposed)
        ).allowed:
            break
        permitted.append(proposed)
    assert len(permitted) == limits.max_tool_calls
    for metric, value in {
        "retries": 3,
        "model_tokens": 32769,
        "concurrent_runs": 5,
        "requests_per_minute": 61,
    }.items():
        decision = check_hard_limits(limits, TechnicalCounters(**{metric: value}))
        assert not decision.allowed and decision.reasons == (metric,)
