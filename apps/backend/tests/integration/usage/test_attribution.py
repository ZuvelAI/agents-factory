import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from apps.backend.tests.integration.runtime.test_agent_turn import _seed_inbound
from apps.backend.tests.usage_support import NOW, event, price
from agents_factory.modules.usage.aggregates import estimate_margin, summarize
from agents_factory.modules.usage.models import Money, UsageConfiguration
from agents_factory.modules.usage.recorder import UsageConflict, UsageRecorder


async def test_two_tenants_concurrent_idempotent_attribution_and_unknown_costs(
    session_factory,
):
    a, ca, _ = await _seed_inbound(session_factory)
    b, cb, _ = await _seed_inbound(session_factory)
    a, b = (
        replace(a, actor_type="system", actor_id=uuid4()),
        replace(b, actor_type="system", actor_id=uuid4()),
    )
    recorder, card = UsageRecorder(session_factory), price()
    admin = replace(a, actor_type="platform_admin")
    await recorder.configure(
        context=admin,
        configuration=UsageConfiguration(prices=(card,)),
        expected_revision=0,
    )
    ea = event().model_copy(update={"conversation_id": ca, "run_id": uuid4()})
    eb = event().model_copy(update={"conversation_id": cb})
    first, duplicate, other = await asyncio.gather(
        recorder.record(context=a, event=ea),
        recorder.record(context=a, event=ea),
        recorder.record(context=b, event=eb),
    )
    assert first.id == duplicate.id and first.tenant_id != other.tenant_id
    assert first.quote.amount == Decimal("0.00037") and other.quote.amount is None
    with pytest.raises(UsageConflict, match="reference_unavailable"):
        await recorder.record(
            context=b, event=ea.model_copy(update={"source_key": "foreign:reference"})
        )
    with pytest.raises(UsageConflict, match="idempotency_conflict"):
        await recorder.record(
            context=a,
            event=ea.model_copy(update={"product": "changed", "model": "changed"}),
        )
    for dimension in (
        "tenant",
        "run",
        "conversation",
        "action",
        "case",
        "model",
        "kind",
    ):
        report = await summarize(
            recorder,
            context=a,
            start=NOW,
            end=NOW + timedelta(days=1),
            dimension=dimension,
        )
        assert (
            len(report.groups) == 1
            and report.groups[0].records == 1
            and report.groups[0].complete_cost
        )
        assert report.groups[0].reasoning_tokens == 10
    unknown_report = await summarize(
        recorder, context=b, start=NOW, end=NOW + timedelta(days=1)
    )
    assert not unknown_report.groups[0].complete_cost
    margin = estimate_margin(
        Money(amount=Decimal(1), currency="USD"), unknown_report.groups
    )
    assert margin.gross_profit is None and margin.reason == "unknown_cost"
    assert estimate_margin(
        Money(amount=Decimal(1), currency="USD"), report.groups
    ).gross_profit == Decimal("0.99963")
    async with session_factory.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.usage_records")) == 2
        )


async def test_configuration_revision_and_immutable_historical_pricing(session_factory):
    context, _, _ = await _seed_inbound(session_factory)
    context = replace(context, actor_type="platform_admin", actor_id=uuid4())
    recorder, card = UsageRecorder(session_factory), price()
    await recorder.configure(
        context=context,
        configuration=UsageConfiguration(prices=(card,)),
        expected_revision=0,
    )
    before = await recorder.record(context=context, event=event())
    future = card.model_copy(
        update={"id": uuid4(), "effective_from": NOW + timedelta(days=1)}
    )
    await recorder.configure(
        context=context,
        configuration=UsageConfiguration(prices=(card, future)),
        expected_revision=1,
    )
    replay = await recorder.record(context=context, event=event())
    assert replay.id == before.id and replay.configuration_revision == 1
    assert replay.quote.price_version == card.id
    with pytest.raises(UsageConflict, match="configuration_conflict"):
        await recorder.configure(
            context=context,
            configuration=UsageConfiguration(prices=(card, future)),
            expected_revision=1,
        )
    with pytest.raises(UsageConflict, match="price_versions_are_immutable"):
        await recorder.configure(
            context=context, configuration=UsageConfiguration(), expected_revision=2
        )
    with pytest.raises(UsageConflict, match="admin_required"):
        await recorder.configure(
            context=replace(context, actor_type="system"),
            configuration=UsageConfiguration(prices=(card, future)),
            expected_revision=2,
        )
