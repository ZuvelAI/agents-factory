from decimal import Decimal
from typing import Literal

from pydantic import Field

from agents_factory.modules.usage.models import (
    CommercialPolicy,
    Count,
    Money,
    TechnicalLimits,
    UsageModel,
)


class UsageTotals(UsageModel):
    messages: Count | None = None
    conversations: Count | None = None
    model_tokens: Count | None = None
    cost: Money | None = None
    storage_bytes: Count | None = None
    concurrent_runs: Count | None = None
    tool_calls: Count | None = None


class QuotaSignal(UsageModel):
    metric: str
    state: Literal["within_budget", "alert", "grace_overage", "unknown"]
    percentage: Decimal | None
    thresholds: tuple[int, ...] = ()


def commercial_signals(
    policy: CommercialPolicy, totals: UsageTotals
) -> tuple[QuotaSignal, ...]:
    signals = []
    for metric in (
        "messages",
        "conversations",
        "model_tokens",
        "cost",
        "storage_bytes",
        "concurrent_runs",
        "tool_calls",
    ):
        ceiling = getattr(policy, metric)
        if ceiling is None:
            continue
        used = getattr(totals, metric)
        if metric == "cost":
            if used is not None and used.currency != ceiling.currency:
                used = None  # No implicit FX conversion or mixed-currency budget.
            ceiling, used = ceiling.amount, None if used is None else used.amount
        if used is None:
            signals.append(QuotaSignal(metric=metric, state="unknown", percentage=None))
            continue
        percentage = (
            Decimal(100) if ceiling == 0 else Decimal(used) * 100 / Decimal(ceiling)
        )
        thresholds = tuple(t for t in policy.alert_percentages if percentage >= t)
        signals.append(
            QuotaSignal(
                metric=metric,
                state="grace_overage"
                if percentage >= 100
                else "alert"
                if thresholds
                else "within_budget",
                percentage=percentage,
                thresholds=thresholds,
            )
        )
    return tuple(signals)


class TechnicalCounters(UsageModel):
    tool_calls: Count = 0
    retries: Count = 0
    model_tokens: Count = 0
    concurrent_runs: Count = 0
    requests_per_minute: Count = 0


class HardLimitDecision(UsageModel):
    allowed: bool
    reasons: tuple[str, ...] = Field(default=())


def check_hard_limits(
    limits: TechnicalLimits, proposed: TechnicalCounters
) -> HardLimitDecision:
    """Evaluate the projected counters including the proposed next operation.

    Callers must serialize/reserve shared concurrency/rate counters. This pure
    decision does not claim to acquire distributed capacity or intercept runtime I/O.
    """
    reasons = tuple(
        metric
        for metric, maximum in (
            ("tool_calls", limits.max_tool_calls),
            ("retries", limits.max_retries),
            ("model_tokens", limits.max_model_tokens),
            ("concurrent_runs", limits.max_concurrent_runs),
            ("requests_per_minute", limits.max_requests_per_minute),
        )
        if getattr(proposed, metric) > maximum
    )
    return HardLimitDecision(allowed=not reasons, reasons=reasons)
