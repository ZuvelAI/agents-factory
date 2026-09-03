import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import text

from apps.backend.tests.integration.runtime.test_agent_turn import _seed_inbound, _spec
from apps.backend.tests.runtime_usage_support import LocalModel, LocalRunner
from apps.backend.tests.usage_support import price
from agents_factory.common.queue import DurableJobRunner, JobEnvelope
from agents_factory.modules.runtime.openai_adapter import OpenAIAgentsRuntime
from agents_factory.modules.runtime.contracts import RuntimeTool
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.usage.models import (
    CommercialPolicy,
    TechnicalLimits,
    UsageConfiguration,
)
from agents_factory.modules.usage.recorder import UsageRecorder
from agent_worker.jobs import handle_agent_turn


async def queued_turn(sessions, context, conversation):
    async with sessions.begin() as session:
        job = await session.scalar(
            text(
                "UPDATE public.outbox_jobs SET status='queued',max_attempts=10 WHERE tenant_id=:tenant AND topic='agent.turn' RETURNING id"
            ),
            {"tenant": context.tenant_id},
        )
    assert job is not None
    return JobEnvelope(
        job_id=job,
        tenant_id=context.tenant_id,
        kind="agent.turn",
        aggregate_id=conversation,
    )


class Specs:
    def __init__(self, *specs):
        self.specs = {spec.tenant_id: spec for spec in specs}

    async def get_active(self, *, tenant_id):
        return self.specs[tenant_id]


async def configure(sessions, context, **technical):
    card = price().model_copy(
        update={
            "provider": "openai",
            "product": "gpt-5.6-luna",
            "effective_from": datetime(2000, 1, 1, tzinfo=UTC),
        }
    )
    await UsageRecorder(sessions).configure(
        context=replace(context, actor_id=uuid4(), actor_type="platform_admin"),
        configuration=UsageConfiguration(
            prices=(card,),
            # A deliberately exhausted commercial budget is not a hard stop.
            commercial=CommercialPolicy(model_tokens=0),
            technical=TechnicalLimits(**technical),
        ),
        expected_revision=0,
    )


async def test_worker_attributes_two_tenants_and_preserves_runaway_usage_after_rollback(
    session_factory,
):
    a, ca, _ = await _seed_inbound(session_factory)
    b, cb, _ = await _seed_inbound(session_factory)
    await configure(session_factory, a, max_tool_calls=1)
    await configure(session_factory, b, max_tool_calls=1)
    ea, eb = (
        await queued_turn(session_factory, a, ca),
        await queued_turn(session_factory, b, cb),
    )
    models = {a.tenant_id: LocalModel(), b.tenant_id: LocalModel(tool_calls=1)}
    invoked = []

    async def lookup(context, arguments):
        invoked.append(context.tenant_id)
        return {"found": True}

    tool = RuntimeTool(
        name="orders.lookup",
        capability="orders",
        description="Local fixture",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=lookup,
    )
    specs = Specs(
        _spec(a.tenant_id),
        replace(
            _spec(b.tenant_id),
            active_capabilities=frozenset({"orders"}),
            permitted_tools=frozenset({"orders.lookup"}),
        ),
    )

    class Runtime:
        async def run(self, turn):
            return await OpenAIAgentsRuntime(
                runner=LocalRunner(models[turn.trace.tenant_id]), require_api_key=False
            ).run(turn)

    async def handler(envelope):
        await handle_agent_turn(
            envelope=envelope,
            database=SimpleNamespace(session_factory=session_factory),
            runtime=Runtime(),
            agent_specs=specs,
            tools=RuntimeToolRegistry((tool,)),
        )

    queue = DurableJobRunner(session_factory=session_factory)
    success, stopped = await asyncio.gather(
        queue.run(envelope=ea, handler=handler), queue.run(envelope=eb, handler=handler)
    )
    assert success.status == "succeeded" and stopped.status == "dead_letter"
    assert (await queue.run(envelope=ea, handler=handler)).status == "already_complete"
    assert invoked == [b.tenant_id]
    assert len(models[a.tenant_id].calls) == 1 and len(models[b.tenant_id].calls) == 2
    async with session_factory.begin() as session:
        records = (
            (
                await session.execute(
                    text(
                        "SELECT tenant_id,kind,event,cost_amount,run_id FROM public.usage_records"
                    )
                )
            )
            .mappings()
            .all()
        )
        ar = [r for r in records if r["tenant_id"] == a.tenant_id]
        br = [r for r in records if r["tenant_id"] == b.tenant_id]
        assert len(ar) == 1 and len(br) == 3
        assert ar[0]["cost_amount"] == Decimal("0.000023")
        assert ar[0]["event"]["measurements"]["cached_input_tokens"] == 2
        assert ar[0]["event"]["conversation_id"] == str(ca)
        assert all(r["event"]["conversation_id"] == str(cb) for r in br)
        assert len({r["run_id"] for r in br}) == 1
        assert ar[0]["run_id"] != br[0]["run_id"]
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.messages WHERE tenant_id=:tenant AND sender_type='ai'"
                ),
                {"tenant": b.tenant_id},
            )
            == 0
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE tenant_id=:tenant AND event_type='usage.runtime_stopped'"
                ),
                {"tenant": b.tenant_id},
            )
            == 1
        )


async def test_worker_retry_budget_prevents_another_provider_request(session_factory):
    context, conversation, _ = await _seed_inbound(session_factory)
    await configure(session_factory, context, max_retries=0)
    envelope = await queued_turn(session_factory, context, conversation)

    class FailingModel(LocalModel):
        async def get_response(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError("synthetic transport failure with no usage")

    model = FailingModel()

    async def handler(current):
        await handle_agent_turn(
            envelope=current,
            database=SimpleNamespace(session_factory=session_factory),
            runtime=OpenAIAgentsRuntime(
                runner=LocalRunner(model), require_api_key=False
            ),
            agent_specs=Specs(_spec(context.tenant_id)),
            tools=RuntimeToolRegistry(()),
        )

    queue = DurableJobRunner(session_factory=session_factory)
    assert (await queue.run(envelope=envelope, handler=handler)).status == "retry"
    assert (await queue.run(envelope=envelope, handler=handler)).status == "dead_letter"
    assert (
        await queue.run(envelope=envelope, handler=handler)
    ).status == "already_complete"
    assert len(model.calls) == 1
    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text("SELECT event,cost_amount FROM public.usage_records")
                )
            )
            .mappings()
            .one()
        )
        assert row["event"]["measurements"]["requests"] == 1
        assert row["event"]["measurements"]["input_tokens"] is None
        assert row["cost_amount"] is None
        audit = await session.scalar(
            text(
                "SELECT payload FROM public.audit_events WHERE event_type='usage.runtime_stopped'"
            )
        )
        assert audit["reason_code"] == "runtime_retry_limit"
        assert audit["attempt_number"] == 2
