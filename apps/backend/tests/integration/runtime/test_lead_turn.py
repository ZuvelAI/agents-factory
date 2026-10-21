"""Real transaction boundaries with a fake model; never call Meta/OpenAI."""

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from agents_factory.modules.agent_factory.models import AgentSpec, VersionReference
from agents_factory.modules.leads.turn_effects import LeadAuthorityChanged
from agents_factory.modules.runtime.contracts import (
    AgentTurnResult,
    RuntimeToolCall,
    RuntimeUsage,
    ToolInvocationContext,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.runtime.turn_service import AgentTurnService
from apps.backend.tests.integration.test_lead_capture import seed, inbound, rows, TEXT
from apps.backend.tests.unit.agent_factory.test_onboarding_projection import (
    inputs,
    project,
)


async def published(factory, capability_version="1.0.0"):
    world = await seed(factory)
    world = (*world[:4], uuid4(), *world[5:])
    config, knowledge = inputs()
    configuration = project(config, knowledge).model_copy(
        update={
            "capabilities": (
                VersionReference(name="lead_capture", version=capability_version),
            ),
            "permitted_tools": ("lead_capture.propose", "lead_capture.suppress"),
        }
    )
    version = AgentSpec(
        tenant_id=world[0].tenant_id,
        agent_instance_id=world[3],
        version_id=world[4],
        version_number=2,
        configuration=configuration,
    )
    async with factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.agent_spec_versions(id,tenant_id,agent_instance_id,version_number,state,configuration) VALUES(:id,:tenant,:agent,2,'DRAFT',:configuration)"
            ).bindparams(bindparam("configuration", type_=JSONB)),
            {
                "id": world[4],
                "tenant": world[0].tenant_id,
                "agent": world[3],
                "configuration": configuration.model_dump(mode="json"),
            },
        )
        await session.execute(
            text(
                "UPDATE public.agent_spec_versions SET compiled_spec=:spec,compiled_digest=:digest,state='TEST' WHERE id=:id"
            ).bindparams(bindparam("spec", type_=JSONB)),
            {
                "id": world[4],
                "spec": version.model_dump(mode="json"),
                "digest": version.digest(),
            },
        )
        for state in ("QUALITY_GATE", "PRODUCTION"):
            await session.execute(
                text("UPDATE public.agent_spec_versions SET state=:state WHERE id=:id"),
                {"state": state, "id": world[4]},
            )
        await session.execute(
            text(
                "INSERT INTO public.account_agent_bindings(tenant_id,whatsapp_account_id,agent_instance_id,version_id,revision) VALUES(:tenant,:account,:agent,:version,1)"
            ),
            {
                "tenant": world[0].tenant_id,
                "account": world[1],
                "agent": world[3],
                "version": world[4],
            },
        )
    return world, version.to_runtime_snapshot(active=True)


@dataclass
class Provider:
    snapshot: object

    async def get_active(self, *, tenant_id):
        return self.snapshot


async def test_unsupported_published_capability_version_never_runs_model(
    session_factory,
):
    world, snapshot = await published(session_factory, capability_version="999.0.0")
    message, _ = await inbound(session_factory, world)
    runtime = PreparedRuntime()
    with pytest.raises(LeadAuthorityChanged):
        await run(session_factory, world, snapshot, message, runtime)
    assert runtime.calls == 0
    assert await rows(session_factory, "lead_prospects") == []


class PreparedRuntime:
    def __init__(self, after=None, invalid=False, duplicate=False):
        self.after, self.invalid, self.duplicate, self.calls = (
            after,
            invalid,
            duplicate,
            0,
        )

    async def run(self, turn):
        self.calls += 1
        assert {tool.name for tool in turn.tools} == {
            "lead_capture.propose",
            "lead_capture.suppress",
        }
        args = {
            "operation": "CAPTURE",
            "service_interest": "Agente de ventas",
            "evidence": [
                {"message_id": str(turn.trace.inbound_message_id), "quote": TEXT}
            ],
        }
        if self.invalid:
            args["declared_company"] = "Inventada"
            output = {"saved": True, "simulated": True}
        else:
            invocation = ToolInvocationContext(
                turn.trace.tenant_id,
                turn.trace.conversation_id,
                turn.trace.inbound_message_id,
                turn.trace.correlation_id,
            )
            output = await turn.tools[0].handler(invocation, args)
        if self.after:
            await self.after()
        call = RuntimeToolCall("lead_capture.propose", args, output)
        return AgentTurnResult(
            "Claro, ¿qué proceso deseas mejorar?",
            (call, call) if self.duplicate else (call,),
            RuntimeUsage(1, 10, 0, 10, 0, 20),
            None,
        )


async def run(factory, world, snapshot, message_id, runtime):
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        return await AgentTurnService(
            session=session,
            context=world[0],
            runtime=runtime,
            agent_specs=Provider(snapshot),
            tools=RuntimeToolRegistry(()),
        ).process(conversation_id=world[2], inbound_message_id=message_id)


async def test_prospect_reply_outbox_and_audit_are_atomic_and_replay_safe(
    session_factory,
):
    world, snapshot = await published(session_factory)
    message, _ = await inbound(session_factory, world)
    runtime = PreparedRuntime()
    result = await run(session_factory, world, snapshot, message, runtime)
    assert result.status == "completed"
    assert (
        await run(session_factory, world, snapshot, message, runtime)
    ).status == "already_processed"
    assert runtime.calls == 1
    assert len(await rows(session_factory, "lead_prospects")) == 1
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='outbound.text'"
                )
            )
            == 1
        )
        metadata = await session.scalar(
            text(
                "SELECT runtime_metadata FROM public.messages WHERE direction='outbound'"
            )
        )
        assert "arguments" not in metadata["tool_calls"][0]
        assert TEXT not in str(metadata)
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE event_type='agent.turn.completed'"
                )
            )
            == 1
        )


async def test_two_simultaneous_turns_commit_one_capture(session_factory):
    world, snapshot = await published(session_factory)
    message, _ = await inbound(session_factory, world)
    barrier = asyncio.Barrier(2)

    async def together():
        await barrier.wait()

    results = await asyncio.gather(
        *(
            run(
                session_factory,
                world,
                snapshot,
                message,
                PreparedRuntime(after=together),
            )
            for _ in range(2)
        )
    )
    assert {result.status for result in results} == {"completed", "already_processed"}
    assert len(await rows(session_factory, "lead_capture_events")) == 1


async def test_human_takeover_after_model_preparation_discards_capture(session_factory):
    world, snapshot = await published(session_factory)
    message, _ = await inbound(session_factory, world)

    async def human():
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "UPDATE public.conversations SET control_state='HUMAN_ACTIVE' WHERE id=:id"
                ),
                {"id": world[2]},
            )

    result = await run(
        session_factory, world, snapshot, message, PreparedRuntime(after=human)
    )
    assert result.status == "blocked_by_conversation_control"
    assert await rows(session_factory, "lead_prospects") == []
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE direction='outbound'")
            )
            == 0
        )


async def test_binding_revision_changed_during_model_discards_everything(
    session_factory,
):
    world, snapshot = await published(session_factory)
    message, _ = await inbound(session_factory, world)

    async def rebind():
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "UPDATE public.account_agent_bindings SET revision=2 WHERE whatsapp_account_id=:account"
                ),
                {"account": world[1]},
            )

    result = await run(
        session_factory, world, snapshot, message, PreparedRuntime(after=rebind)
    )
    assert result.status == "blocked_by_agent_operation"
    assert await rows(session_factory, "lead_prospects") == []
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE direction='outbound'")
            )
            == 0
        )


async def test_account_deactivated_during_model_discards_capture(session_factory):
    from datetime import UTC, datetime
    from agents_factory.modules.whatsapp.account_service import (
        WhatsAppAccountRepository,
    )

    world, snapshot = await published(session_factory)
    message, _ = await inbound(session_factory, world)

    async def deactivate():
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await WhatsAppAccountRepository(session).deactivate(
                context=world[0], account_id=world[1], checked_at=datetime.now(UTC)
            )

    with pytest.raises(LeadAuthorityChanged):
        await run(
            session_factory, world, snapshot, message, PreparedRuntime(after=deactivate)
        )
    assert await rows(session_factory, "lead_prospects") == []


@pytest.mark.parametrize("invalid,duplicate", [(True, False), (False, True)])
async def test_fake_saved_output_or_duplicate_proposal_never_bypasses_validation(
    session_factory, invalid, duplicate
):
    world, snapshot = await published(session_factory)
    message, _ = await inbound(session_factory, world)
    with pytest.raises(ValueError):
        await run(
            session_factory,
            world,
            snapshot,
            message,
            PreparedRuntime(invalid=invalid, duplicate=duplicate),
        )
    assert await rows(session_factory, "lead_prospects") == []


async def test_outbox_failure_rolls_back_prospect_and_reply(
    session_factory, monkeypatch
):
    from agents_factory.common.outbox import OutboxService

    world, snapshot = await published(session_factory)
    message, _ = await inbound(session_factory, world)

    async def failed(*args, **kwargs):
        raise RuntimeError("local test outbox failure")

    monkeypatch.setattr(OutboxService, "enqueue", failed)
    with pytest.raises(RuntimeError, match="local test outbox failure"):
        await run(session_factory, world, snapshot, message, PreparedRuntime())
    assert await rows(session_factory, "lead_prospects") == []
    assert await rows(session_factory, "lead_capture_events") == []
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE direction='outbound'")
            )
            == 0
        )


async def test_direct_refusal_is_ingested_without_model_or_prospect_even_under_human_control(
    session_factory,
):
    from agents_factory.modules.conversations.models import AwaitingHumanPolicy
    from agents_factory.modules.conversations.service import ConversationService

    world, _ = await published(session_factory)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.conversations SET control_state='HUMAN_ACTIVE' WHERE id=:id"
            ),
            {"id": world[2]},
        )
    event, _ = await inbound(
        session_factory, world, "No guardes mis datos como prospecto", event_only=True
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        result = await ConversationService(
            session=session,
            context=world[0],
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(event)
        assert not result.response_queued
    assert await rows(session_factory, "lead_prospects") == []
    (subject,) = await rows(session_factory, "lead_subjects")
    assert subject["capture_suppressed"]
    assert subject["suppression_message_id"] == result.message_id


async def test_refusal_does_not_create_lead_storage_for_company_that_never_used_capture(
    session_factory,
):
    from agents_factory.modules.conversations.models import AwaitingHumanPolicy
    from agents_factory.modules.conversations.service import ConversationService

    world = await seed(session_factory)
    event, _ = await inbound(
        session_factory, world, "No registres mis datos", event_only=True
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await ConversationService(
            session=session,
            context=world[0],
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(event)
    assert await rows(session_factory, "lead_subjects") == []


async def test_binding_writer_waits_for_existing_runtime_lifecycle_fence(
    session_factory,
):
    from agents_factory.modules.leads.turn_effects import LeadTurnEffects
    from agents_factory.modules.agent_factory.channel_binding import (
        AccountAgentBindingRepository,
    )
    from agents_factory.modules.agent_factory.repository import AgentSpecRepository
    from agents_factory.modules.runtime.contracts import (
        AgentTurnInput,
        RuntimeTraceMetadata,
    )

    world, snapshot = await published(session_factory)
    message, messages = await inbound(session_factory, world)
    turn = AgentTurnInput(
        snapshot,
        messages,
        (),
        RuntimeTraceMetadata(
            world[0].tenant_id,
            world[2],
            message,
            world[0].correlation_id,
            snapshot.id,
            snapshot.digest,
        ),
    )

    async def bind():
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            version = await AgentSpecRepository(session, world[0]).get_version(world[4])
            return await AccountAgentBindingRepository(session, world[0]).bind(
                world[1], version, expected_revision=1, action="PUBLISH"
            )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        effects = LeadTurnEffects(session, world[0])
        authority = await effects.prepare(turn)
        await effects.lock_current(turn, authority)
        writer = asyncio.create_task(bind())
        done, pending = await asyncio.wait({writer}, timeout=0.1)
        assert not done and pending == {writer}
    assert (await asyncio.wait_for(writer, timeout=2)).revision == 2
