from dataclasses import replace

import pytest
from sqlalchemy import text

from agents_factory.common.queue import JobEnvelope
from agents_factory.modules.audio_ingestion.preflight import AudioJobPreflight
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.runtime.turn_service import (
    AgentTurnService,
    Milestone2AgentSpecProvider,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from apps.backend.tests.integration.runtime.test_agent_turn import (
    _FakeRuntime,
    _SpecProvider,
)
from apps.backend.tests.integration.test_lead_capture import inbound
from apps.backend.tests.integration.audio_fixtures import audio_world, audio_message
from apps.backend.tests.integration.test_audio_orchestration import setup, state


async def run_turn(factory, world, message, runtime, snapshot=None):
    snapshot = snapshot or await Milestone2AgentSpecProvider(
        "Company brand instructions"
    ).get_active(tenant_id=world[0].tenant_id)
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        return await AgentTurnService(
            session=session,
            context=world[0],
            runtime=runtime,
            agent_specs=_SpecProvider(snapshot),
            tools=RuntimeToolRegistry(()),
        ).process(conversation_id=world[2], inbound_message_id=message)


async def test_audio_waiting_does_not_starve_other_tenant_text(session_factory):
    from agents_factory.common.outbox import OutboxService
    from agents_factory.common.queue import DurableJobRunner
    from agents_factory.modules.audio_ingestion.capacity import AudioCapacityGuard
    from apps.backend.tests.integration.test_lead_capture import seed

    world, message, envelope, service, _, _ = await setup(session_factory)
    other = await seed(session_factory)
    written, _ = await inbound(session_factory, other, "Consulta escrita")
    async with session_factory.begin() as session:
        await OutboxService(session).enqueue(
            context=other[0],
            topic="agent.turn",
            idempotency_key=f"agent.turn:{written}",
            payload={
                "aggregate_id": str(other[2]),
                "conversation_id": str(other[2]),
                "inbound_message_id": str(written),
            },
        )
        job = await session.scalar(
            text("SELECT id FROM public.outbox_jobs WHERE tenant_id=:t"),
            {"t": other[0].tenant_id},
        )
        await session.execute(
            text("UPDATE public.outbox_jobs SET status='queued' WHERE id=:j"),
            {"j": job},
        )
    runner = DurableJobRunner(
        session_factory=session_factory,
        preflight=AudioJobPreflight(session_factory).admit,
    )
    runtime = _FakeRuntime()

    async def handle(envelope):
        await run_turn(session_factory, other, written, runtime)

    guard = AudioCapacityGuard(session_factory)
    async with guard.hold(world[0].tenant_id), guard.hold(other[0].tenant_id):
        result = await runner.run(
            envelope=JobEnvelope(job, other[0].tenant_id, "agent.turn", other[2]),
            handler=handle,
        )
    assert result.status == "succeeded" and len(runtime.turns) == 1
    assert runtime.turns[0].messages[-1].text == "Consulta escrita"


async def test_revoked_account_after_ready_cannot_run_agent_or_capture(session_factory):
    world, message, envelope, service, _, _ = await setup(session_factory)
    await service.process(envelope)
    async with session_factory.begin() as session:
        await session.execute(
            text("UPDATE public.whatsapp_accounts SET status='inactive' WHERE id=:id"),
            {"id": world[1]},
        )
    runtime = _FakeRuntime()
    assert (
        await run_turn(session_factory, world, message, runtime)
    ).status == "blocked_by_conversation_control"
    assert not runtime.turns


@pytest.mark.parametrize("mode", ["API_ONLY", "COEXISTENCE"])
async def test_audio_default_supports_existing_and_new_tenants_without_republication(
    session_factory, mode
):
    world, message = await audio_world(session_factory)
    async with session_factory.begin() as session:
        event = await session.scalar(
            text("SELECT source_event_id FROM public.messages WHERE id=:m"),
            {"m": message},
        )
        await session.execute(
            text("DELETE FROM public.messages WHERE id=:m"), {"m": message}
        )
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET mode=:mode,coexistence_eligibility='ELIGIBLE' WHERE id=:a"
            ),
            {"a": world[1], "mode": mode},
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        ingested = await ConversationService(
            session=session,
            context=world[0],
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(event)
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.whatsapp_audio_transcriptions WHERE tenant_id=:t"
                ),
                {"t": world[0].tenant_id},
            )
            == 1
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE tenant_id=:t AND topic='agent.turn'"
                ),
                {"t": world[0].tenant_id},
            )
            == 0
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE tenant_id=:t AND topic='whatsapp.audio.transcribe'"
                ),
                {"t": world[0].tenant_id},
            )
            == 1
        )
    assert ingested.response_queued


async def test_audio_then_text_preserves_preparation_order(session_factory):
    world, message, envelope, service, _, transcriber = await setup(session_factory)
    later, _ = await inbound(session_factory, world, "¿Cuánto vale?", sequence=2)
    runtime = _FakeRuntime()
    waiting = await run_turn(session_factory, world, later, runtime)
    assert waiting.status == "audio_not_ready"
    assert runtime.turns == []
    await service.process(envelope)
    snapshot = await Milestone2AgentSpecProvider("Brand unchanged").get_active(
        tenant_id=world[0].tenant_id
    )
    assert (
        await run_turn(session_factory, world, message, runtime, snapshot)
    ).status == "completed"
    assert [m.text for m in runtime.turns[0].messages] == ["Quiero un agente"]
    assert runtime.turns[0].agent_spec == snapshot
    assert (
        await run_turn(session_factory, world, later, runtime)
    ).status == "completed"
    assert runtime.turns[-1].messages[0].text == "Quiero un agente"
    assert runtime.turns[-1].messages[-1].text == "¿Cuánto vale?"
    assert transcriber.transcribe.await_count == 1


async def test_two_audio_notes_preserve_sequence(session_factory):
    world, message, envelope, service, _, transcriber = await setup(session_factory)
    later = await audio_message(session_factory, world, sequence=2)
    async with session_factory.begin() as session:
        from agents_factory.modules.audio_ingestion.repository import AudioRepository

        await AudioRepository(session, world[0]).enqueue(later)
        job = await session.scalar(
            text(
                "SELECT id FROM public.outbox_jobs WHERE topic='whatsapp.audio.transcribe' AND tenant_id=:t AND payload->>'inbound_message_id'=:m"
            ),
            {"t": world[0].tenant_id, "m": str(later)},
        )
    second = JobEnvelope(job, world[0].tenant_id, "whatsapp.audio.transcribe", world[2])
    preflight = AudioJobPreflight(session_factory)
    assert await preflight.check(second) is not None
    await service.process(envelope)
    assert await preflight.check(second) is None
    from agents_factory.modules.audio_ingestion.models import (
        AudioTranscript,
        TRANSCRIPTION_MODEL,
    )

    transcriber.transcribe.return_value = AudioTranscript(
        "Quiero conocer precios", TRANSCRIPTION_MODEL
    )
    await service.process(second)
    runtime = _FakeRuntime()
    assert (
        await run_turn(session_factory, world, message, runtime)
    ).status == "completed"
    assert [m.text for m in runtime.turns[-1].messages] == ["Quiero un agente"]
    assert (
        await run_turn(session_factory, world, later, runtime)
    ).status == "completed"
    assert runtime.turns[-1].messages[0].text == "Quiero un agente"
    assert runtime.turns[-1].messages[-1].text == "Quiero conocer precios"
    assert transcriber.transcribe.await_count == 2


async def test_inactive_agent_and_human_chat_do_not_transcribe(session_factory):
    world, message, envelope, service, _, transcriber = await setup(session_factory)
    snapshot = await Milestone2AgentSpecProvider().get_active(
        tenant_id=world[0].tenant_id
    )
    service.authority.provider = lambda *args: _SpecProvider(
        replace(snapshot, active=False)
    )
    await service.process(envelope)
    assert (await state(session_factory, message))[0]["status"] == "CANCELLED"
    assert transcriber.transcribe.await_count == 0


async def test_voice_kill_switch_stops_new_paid_work_without_affecting_text(
    session_factory,
):
    world, message, envelope, service, downloader, transcriber = await setup(
        session_factory
    )
    service.enabled = lambda: False
    await service.process(envelope)
    assert (await state(session_factory, message))[0]["status"] == "FAILED"
    assert (await state(session_factory, message))[1] == 1
    downloader.download.assert_not_called()
    transcriber.transcribe.assert_not_called()
    later, _ = await inbound(session_factory, world, "Quiero información", sequence=3)
    runtime = _FakeRuntime()
    assert (
        await run_turn(session_factory, world, later, runtime)
    ).status == "completed"


async def test_non_audio_and_legacy_dead_letters_do_not_enter_voice_pipeline(
    session_factory,
):
    world, message = await audio_world(session_factory)
    runtime = _FakeRuntime()
    assert (
        await run_turn(session_factory, world, message, runtime)
    ).status == "audio_not_ready"
    assert not runtime.turns
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.whatsapp_audio_transcriptions WHERE tenant_id=:t"
                ),
                {"t": world[0].tenant_id},
            )
            == 0
        )
