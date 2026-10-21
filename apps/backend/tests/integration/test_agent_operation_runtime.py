from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from apps.backend.tests.integration.test_agent_message_admission import (
    operation_world as _operation_world,
    admit_fixture,
    change_state,
)
from apps.backend.tests.integration.runtime.test_agent_turn import (
    _FakeRuntime,
    _SpecProvider,
)
from agents_factory.modules.runtime.turn_service import (
    AgentTurnService,
    Milestone2AgentSpecProvider,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.conversations.service import ConversationService

operation_world = _operation_world


async def incoming(factory, world, *, at=None):
    admission = await admit_fixture(factory, world, occurred_at=at or datetime.now(UTC))
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        return await ConversationService(
            session=session,
            context=world[0],
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(admission.source_event_id)


async def run_turn(factory, world, message, runtime):
    snapshot = await Milestone2AgentSpecProvider().get_active(
        tenant_id=world[0].tenant_id
    )
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        return await AgentTurnService(
            session=session,
            context=world[0],
            runtime=runtime,
            agent_specs=_SpecProvider(snapshot),
            tools=RuntimeToolRegistry(()),
        ).process(
            conversation_id=message.conversation_id,
            inbound_message_id=message.message_id,
        )


@pytest.mark.asyncio
async def test_pause_before_turn_avoids_model_and_reply(
    session_factory, operation_world
):
    message = await incoming(session_factory, operation_world)
    await change_state(session_factory, operation_world, False, 1)
    runtime = _FakeRuntime()
    result = await run_turn(session_factory, operation_world, message, runtime)
    assert result.status == "blocked_by_agent_operation"
    assert not runtime.turns
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE sender_type='ai'")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_pause_resume_during_model_discards_old_reply(
    session_factory, operation_world
):
    message = await incoming(session_factory, operation_world)

    class PausingRuntime(_FakeRuntime):
        async def run(self, turn):
            await change_state(session_factory, operation_world, False, 1)
            await change_state(session_factory, operation_world, True, 2)
            return await super().run(turn)

    runtime = PausingRuntime()
    result = await run_turn(session_factory, operation_world, message, runtime)
    assert result.status == "blocked_by_agent_operation"
    assert len(runtime.turns) == 1
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE sender_type='ai'")
            )
            == 0
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='outbound.text'"
                )
            )
            == 0
        )
    new = await incoming(
        session_factory, operation_world, at=datetime.now(UTC) + timedelta(seconds=1)
    )
    assert (
        await run_turn(session_factory, operation_world, new, _FakeRuntime())
    ).status == "completed"


async def audio_operation_world(factory, world):
    from uuid import uuid4
    from agents_factory.common.context import TenantContext

    async with factory.begin() as session:
        agent = await session.scalar(
            text(
                "SELECT agent_instance_id FROM public.account_agent_bindings WHERE tenant_id=:t AND whatsapp_account_id=:a"
            ),
            {"t": world[0].tenant_id, "a": world[1]},
        )
    return (
        TenantContext(world[0].tenant_id, uuid4(), "platform_admin", uuid4()),
        world[1],
        agent,
    )


@pytest.mark.asyncio
async def test_audio_paused_before_work_has_no_paid_attempt(session_factory):
    from apps.backend.tests.integration.test_audio_orchestration import setup, state

    world, message, envelope, service, downloader, transcriber = await setup(
        session_factory
    )
    await change_state(
        session_factory, await audio_operation_world(session_factory, world), False, 1
    )
    await service.process(envelope)
    row, replies = await state(session_factory, message)
    assert row["status"] == "CANCELLED" and replies == 0
    assert transcriber.transcribe.await_count == 0
    assert downloader.download.await_count == 0


@pytest.mark.asyncio
async def test_pause_during_transcription_keeps_result_without_agent_job(
    session_factory,
):
    from apps.backend.tests.integration.test_audio_orchestration import setup, state
    from agents_factory.modules.audio_ingestion.models import (
        AudioTranscript,
        TRANSCRIPTION_MODEL,
    )

    async def transcribe(path, inspection):
        control = await audio_operation_world(session_factory, world)
        await change_state(session_factory, control, False, 1)
        await change_state(session_factory, control, True, 2)
        return AudioTranscript("Consulta de prueba", TRANSCRIPTION_MODEL)

    world, message, envelope, service, _, _ = await setup(
        session_factory, transcriber=transcribe
    )
    await service.process(envelope)
    row, replies = await state(session_factory, message)
    assert row["status"] == "READY" and replies == 0
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.outbox_jobs WHERE topic='agent.turn'")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_audio_fallback_after_pause_does_not_reply(session_factory):
    from apps.backend.tests.integration.test_audio_orchestration import setup, state
    from agents_factory.modules.audio_ingestion.fallback import AudioFallbackService

    world, message, _, service, _, _ = await setup(session_factory)
    await change_state(
        session_factory, await audio_operation_world(session_factory, world), False, 1
    )
    await AudioFallbackService(session_factory, world[0], service.authority).finalize(
        message, "audio_download_failed"
    )
    _, replies = await state(session_factory, message)
    assert replies == 0


@pytest.mark.asyncio
async def test_worker_owned_session_releases_transaction_during_provider(
    session_factory, operation_world
):
    message = await incoming(session_factory, operation_world)
    snapshot = await Milestone2AgentSpecProvider().get_active(
        tenant_id=operation_world[0].tenant_id
    )
    async with session_factory() as session:

        class InspectingRuntime(_FakeRuntime):
            async def run(self, turn):
                assert session.in_transaction() is False
                return await super().run(turn)

        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        result = await AgentTurnService(
            session=session,
            session_factory=session_factory,
            context=operation_world[0],
            runtime=InspectingRuntime(),
            agent_specs=_SpecProvider(snapshot),
            tools=RuntimeToolRegistry(()),
        ).process(
            conversation_id=message.conversation_id,
            inbound_message_id=message.message_id,
        )
        await session.commit()
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_tool_after_pause_cannot_start_an_effect(
    session_factory, operation_world
):
    from agents_factory.modules.agent_operations.runtime_guard import guard_tool
    from agents_factory.modules.agent_operations.admission import (
        check_message_eligibility,
    )
    from agents_factory.modules.runtime.contracts import (
        RuntimeTool,
        ToolInvocationContext,
    )
    from agents_factory.modules.runtime.openai_adapter import AgentRuntimeError

    message = await incoming(session_factory, operation_world)
    effects = []

    async def effect(context, arguments):
        effects.append(arguments)
        return {"ok": True}

    async def eligible():
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            return await check_message_eligibility(
                session, operation_world[0], message_id=message.message_id
            )

    tool = guard_tool(
        RuntimeTool(
            "probe.execute", "probe", "Test effect", {"type": "object"}, effect
        ),
        eligible,
    )
    admin = operation_world[0]
    invocation = ToolInvocationContext(
        admin.tenant_id,
        message.conversation_id,
        message.message_id,
        admin.correlation_id,
    )
    assert await tool.handler(invocation, {"before": True}) == {"ok": True}
    await change_state(session_factory, operation_world, False, 1)
    with pytest.raises(AgentRuntimeError, match="agent_operation_ineligible"):
        await tool.handler(invocation, {"after": True})
    assert effects == [{"before": True}]
