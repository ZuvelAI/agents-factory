import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from apps.backend.tests.integration.runtime.test_agent_turn import _seed_inbound, _spec
from apps.backend.tests.integration import test_conversation_lock as redis_fixtures
from apps.backend.tests.integration.usage.test_runtime_usage import Specs, queued_turn
from apps.backend.tests.runtime_usage_support import LocalModel, LocalRunner
from agents_factory.common.deferral import JobDeferred
from agents_factory.common.queue import DurableJobRunner
from agents_factory.modules.runtime.contracts import RuntimeTool
from agents_factory.modules.runtime.errors import AgentRuntimeError
from agents_factory.modules.runtime.openai_adapter import OpenAIAgentsRuntime
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.usage.alerts import list_alerts
from agents_factory.modules.usage.capacity import UsageCapacity
from agents_factory.modules.usage.models import (
    CommercialPolicy,
    Measurements,
    Money,
    QuotaWindow,
    TechnicalLimits,
    UsageConfiguration,
    UsageEvent,
)
from agents_factory.modules.usage.recorder import UsageRecorder
from agent_worker.jobs import handle_agent_turn

local_redis_url = redis_fixtures.local_redis_url
redis_client = redis_fixtures.redis_client


async def save_config(
    sessions, context, *, technical=None, commercial=None, window=None
):
    await UsageRecorder(sessions).configure(
        context=replace(context, actor_id=uuid4(), actor_type="platform_admin"),
        configuration=UsageConfiguration(
            technical=technical or TechnicalLimits(),
            commercial=commercial or CommercialPolicy(),
            quota_window=window,
        ),
        expected_revision=0,
    )


async def test_atomic_capacity_rate_window_and_stale_fencing(redis_client):
    # Independent manager instances share Redis, not process-local counters.
    first, second = UsageCapacity(redis_client), UsageCapacity(redis_client)
    a, b = uuid4(), uuid4()
    limits = TechnicalLimits(max_concurrent_runs=2, max_requests_per_minute=2)

    async def acquire(tenant, manager=first):
        return await manager.acquire(
            tenant_id=tenant, run_id=uuid4(), limits=limits, timeout_seconds=20
        )

    try:
        contenders = await asyncio.gather(
            *(acquire(a, first if i % 2 else second) for i in range(12)),
            return_exceptions=True,
        )
        leases = [v for v in contenders if not isinstance(v, BaseException)]
        assert len(leases) == 2
        assert sum(isinstance(v, JobDeferred) for v in contenders) == 10
        other = await acquire(b)
        await asyncio.gather(*(v.before_model() for v in leases))
        with pytest.raises(AgentRuntimeError, match="runtime_rate_limit"):
            await leases[0].before_model()
        await leases[0].release()
        replacement = await acquire(a, second)
        with pytest.raises(JobDeferred):
            await replacement.before_model()
        await other.before_model()  # Tenant B has its own window.
        # Advance only synthetic reservations; no sleeps or global Redis flush.
        requests_key = first.keys(a)[1]
        members = await redis_client.zrange(requests_key, 0, -1)
        await redis_client.zadd(requests_key, {member: 1 for member in members})
        await replacement.before_model()
        await redis_client.zadd(first.keys(a)[0], {str(replacement.run_id): 1})
        with pytest.raises(AgentRuntimeError, match="runtime_capacity_lost"):
            await replacement.before_tool()
        newest = await acquire(a)
        await replacement.release()  # Stale owner cannot release the new owner.
        await newest.before_tool()
    finally:
        await redis_client.delete(*first.keys(a), *first.keys(b))


async def test_worker_deferral_does_not_spend_retry_budget(
    session_factory, redis_client
):
    context, conversation, _ = await _seed_inbound(session_factory)
    limits = TechnicalLimits(max_concurrent_runs=1, max_retries=0)
    await save_config(session_factory, context, technical=limits)
    envelope = await queued_turn(session_factory, context, conversation)
    async with session_factory.begin() as session:
        await session.execute(
            text("UPDATE public.outbox_jobs SET max_attempts=1 WHERE id=:id"),
            {"id": envelope.job_id},
        )
    capacity, model = UsageCapacity(redis_client), LocalModel()
    held = await capacity.acquire(
        tenant_id=context.tenant_id, run_id=uuid4(), limits=limits, timeout_seconds=30
    )

    async def handler(current):
        await handle_agent_turn(
            envelope=current,
            database=SimpleNamespace(session_factory=session_factory),
            runtime=OpenAIAgentsRuntime(
                runner=LocalRunner(model), require_api_key=False
            ),
            agent_specs=Specs(_spec(context.tenant_id)),
            tools=RuntimeToolRegistry(()),
            capacity=capacity,
        )

    queue = DurableJobRunner(session_factory=session_factory)
    try:
        result = await queue.run(envelope=envelope, handler=handler)
        assert result.status == "deferred" and model.calls == []
        async with session_factory.begin() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT status,available_at>now() AS delayed FROM public.outbox_jobs WHERE id=:id"
                        ),
                        {"id": envelope.job_id},
                    )
                )
                .mappings()
                .one()
            )
            assert row["status"] == "pending" and row["delayed"]
            assert (
                await session.scalar(text("SELECT count(*) FROM public.usage_records"))
                == 0
            )
            # Simulate the due dispatcher; the production dispatcher owns this transition.
            await session.execute(
                text(
                    "UPDATE public.outbox_jobs SET status='queued',available_at=now() WHERE id=:id"
                ),
                {"id": envelope.job_id},
            )
        await held.release()
        assert (
            await queue.run(envelope=envelope, handler=handler)
        ).status == "succeeded"
        assert len(model.calls) == 1
        assert await redis_client.zcard(capacity.keys(context.tenant_id)[0]) == 0
        async with session_factory.begin() as session:
            attempts = (
                await session.execute(
                    text(
                        "SELECT attempt_count,deferral_count FROM public.outbox_jobs WHERE id=:id"
                    ),
                    {"id": envelope.job_id},
                )
            ).one()
            assert tuple(attempts) == (2, 1)
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "UPDATE public.outbox_jobs SET attempt_count=3 WHERE id=:id"
                        ),
                        {"id": envelope.job_id},
                    )
    finally:
        await redis_client.delete(*capacity.keys(context.tenant_id))


async def test_sdk_followup_rate_limit_stops_without_partial_run_replay(
    session_factory, redis_client
):
    context, conversation, _ = await _seed_inbound(session_factory)
    await save_config(
        session_factory, context, technical=TechnicalLimits(max_requests_per_minute=1)
    )
    envelope = await queued_turn(session_factory, context, conversation)
    capacity, model, calls = UsageCapacity(redis_client), LocalModel(tool_calls=1), []

    async def lookup(context, arguments):
        calls.append(context.tenant_id)
        return {"found": True}

    tool = RuntimeTool(
        name="orders.lookup",
        capability="orders",
        description="Synthetic lookup",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=lookup,
    )
    spec = replace(
        _spec(context.tenant_id),
        active_capabilities=frozenset({"orders"}),
        permitted_tools=frozenset({"orders.lookup"}),
    )

    async def handler(current):
        await handle_agent_turn(
            envelope=current,
            database=SimpleNamespace(session_factory=session_factory),
            runtime=OpenAIAgentsRuntime(
                runner=LocalRunner(model), require_api_key=False
            ),
            agent_specs=Specs(spec),
            tools=RuntimeToolRegistry((tool,)),
            capacity=capacity,
        )

    try:
        queue = DurableJobRunner(session_factory=session_factory)
        assert (
            await queue.run(envelope=envelope, handler=handler)
        ).status == "dead_letter"
        assert len(model.calls) == len(calls) == 1
        assert await redis_client.zcard(capacity.keys(context.tenant_id)[0]) == 0
        async with session_factory.begin() as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM public.usage_records"))
                == 2
            )
            audit = await session.scalar(
                text(
                    "SELECT payload FROM public.audit_events WHERE event_type='usage.runtime_stopped'"
                )
            )
            assert audit["reason_code"] == "runtime_rate_limit"
    finally:
        await redis_client.delete(*capacity.keys(context.tenant_id))


async def test_alerts_are_atomic_period_scoped_and_do_not_cut_service(session_factory):
    a, ca, _ = await _seed_inbound(session_factory)
    b, cb, _ = await _seed_inbound(session_factory)
    a, b = replace(a, actor_id=uuid4()), replace(b, actor_id=uuid4())
    now = datetime.now(UTC)
    window = QuotaWindow(start=now - timedelta(hours=1), end=now + timedelta(hours=1))
    policy = CommercialPolicy(model_tokens=100, concurrent_runs=2)
    for context in (a, b):
        await save_config(session_factory, context, commercial=policy, window=window)
    recorder = UsageRecorder(session_factory)

    def event(amount, *, conversation=ca, at=now):
        return UsageEvent(
            source_key=f"case:{uuid4()}",
            occurred_at=at,
            kind="llm",
            provider="fixture",
            product="fixture",
            model="fixture",
            currency="USD",
            conversation_id=conversation,
            measurements=Measurements(input_tokens=amount, output_tokens=0),
        )

    events = [event(35), event(35), event(15), event(15)]
    await asyncio.gather(*(recorder.record(context=a, event=e) for e in events[:2]))
    for e in events[2:]:
        await recorder.record(context=a, event=e)
    await recorder.record(context=a, event=events[-1])  # Idempotent replay.
    await recorder.record(context=b, event=event(10, conversation=cb))
    await recorder.record(context=b, event=event(1000, conversation=cb, at=window.end))
    await asyncio.gather(recorder.check_alerts(a), recorder.check_alerts(a))
    async with recorder.transaction(a) as session:
        page = await list_alerts(session, limit=2)
        assert page.has_more and len(page.alerts) == 2
        tail = await list_alerts(session, before=page.alerts[-1].id, limit=2)
        alerts = (*page.alerts, *tail.alerts)
        assert sorted(v.threshold for v in alerts) == [70, 85, 100]
        assert next(v for v in alerts if v.threshold == 100).state == "grace_overage"
        assert all(v.recorded_data_only for v in alerts)
        assert not tail.has_more
    async with recorder.transaction(b) as session:
        assert (await list_alerts(session)).alerts == ()
    await recorder.check_alerts(a, concurrent_runs=2)
    async with recorder.transaction(a) as session:
        all_alerts = (await list_alerts(session)).alerts
        assert len(all_alerts) == 6
        assert sum(v.metric == "concurrent_runs" for v in all_alerts) == 3
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE event_type='usage.quota_threshold_crossed'"
                )
            )
            == 6
        )


async def test_cost_alerts_preserve_unknown_currency_and_oversized_totals(
    session_factory,
):
    a, _, _ = await _seed_inbound(session_factory)
    b, _, _ = await _seed_inbound(session_factory)
    a, b = replace(a, actor_id=uuid4()), replace(b, actor_id=uuid4())
    now = datetime.now(UTC)
    window = QuotaWindow(start=now - timedelta(hours=1), end=now + timedelta(hours=1))
    for context in (a, b):
        await save_config(
            session_factory,
            context,
            commercial=CommercialPolicy(cost=Money(amount=Decimal(1), currency="USD")),
            window=window,
        )
    recorder = UsageRecorder(session_factory)

    def event(amount, currency="USD"):
        return UsageEvent(
            source_key=f"cost:{uuid4()}",
            occurred_at=now,
            kind="infrastructure",
            provider="fixture",
            product="fixture",
            currency=currency,
            measurements=Measurements(requests=1),
            provider_cost=None
            if amount is None
            else Money(amount=Decimal(amount), currency=currency),
        )

    await recorder.record(context=a, event=event("0.70"))
    await recorder.record(context=a, event=event(None))
    await recorder.record(context=a, event=event("100", "EUR"))
    async with recorder.transaction(a) as session:
        alerts = (await list_alerts(session)).alerts
        assert len(alerts) == 1 and alerts[0].threshold == 70
    # Even individually valid very large costs may exceed the aggregate contract.
    # Both remain recorded; alert calculation must not stop service or invent FX.
    await recorder.record(context=b, event=event("900000000000000000"))
    await recorder.record(context=b, event=event("900000000000000000"))
    async with recorder.transaction(b) as session:
        assert len((await list_alerts(session)).alerts) == 3
        assert (
            await session.scalar(text("SELECT count(*) FROM public.usage_records")) == 2
        )
