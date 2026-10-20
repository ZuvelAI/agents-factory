import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text

from agents_factory.common.queue import DurableJobRunner, JobEnvelope
from agents_factory.modules.audio_ingestion.authorization import AudioAuthority
from agents_factory.modules.audio_ingestion.models import (
    AudioInspection,
    AudioTranscript,
    TRANSCRIPTION_MODEL,
)
from agents_factory.modules.audio_ingestion.preflight import AudioJobPreflight
from agents_factory.modules.audio_ingestion.service import AudioIngestionService
from agents_factory.modules.audio_ingestion.transcriber import AudioTranscriptionError
from agents_factory.modules.runtime.turn_service import Milestone2AgentSpecProvider
from apps.backend.tests.integration.audio_fixtures import audio_world
from apps.backend.tests.integration.test_audio_repository import operation


async def setup(factory, *, transcriber=None, download=None, inspect=None, clock=None):
    world, message = await audio_world(factory)
    await operation(factory, world[0], lambda repo: repo.enqueue(message))
    async with factory.begin() as session:
        job = await session.scalar(
            text(
                "SELECT id FROM public.outbox_jobs WHERE topic='whatsapp.audio.transcribe' AND tenant_id=:t"
            ),
            {"t": world[0].tenant_id},
        )
        await session.execute(
            text("UPDATE public.outbox_jobs SET status='queued' WHERE id=:j"),
            {"j": job},
        )
    envelope = JobEnvelope(
        job, world[0].tenant_id, "whatsapp.audio.transcribe", world[2]
    )
    downloader = SimpleNamespace(
        download=download
        or AsyncMock(return_value=SimpleNamespace(size_bytes=3, sha256="1" * 64))
    )
    inspector = SimpleNamespace(
        inspect=inspect or AsyncMock(return_value=AudioInspection("ogg", "opus", 1, 3))
    )
    transcriber = SimpleNamespace(
        transcribe=transcriber
        or AsyncMock(
            return_value=AudioTranscript("Quiero un agente", TRANSCRIPTION_MODEL)
        )
    )
    authority = AudioAuthority(
        lambda session, context, conversation: Milestone2AgentSpecProvider()
    )
    service = AudioIngestionService(
        factory,
        downloader=downloader,
        inspector=inspector,
        transcriber=transcriber,
        authority=authority,
        **({"clock": clock} if clock else {}),
    )
    return world, message, envelope, service, downloader, transcriber


async def state(factory, message):
    async with factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM public.whatsapp_audio_transcriptions WHERE inbound_message_id=:m"
                    ),
                    {"m": message},
                )
            )
            .mappings()
            .one()
        )
        replies = await session.scalar(
            text(
                "SELECT count(*) FROM public.messages WHERE in_reply_to_message_id=:m"
            ),
            {"m": message},
        )
        return row, replies


async def test_audio_ready_survives_failed_agent_turn(session_factory):
    world, message, envelope, service, downloader, transcriber = await setup(
        session_factory
    )
    await service.process(envelope)
    await service.process(envelope)
    row, replies = await state(session_factory, message)
    assert row["status"] == "READY" and row["transcript"] == "Quiero un agente"
    assert replies == 0
    assert row["duration_seconds"] == 1
    assert row["size_bytes"] == 3
    assert row["actual_sha256"] == "1" * 64
    assert transcriber.transcribe.await_count == downloader.download.await_count == 1
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='agent.turn' AND tenant_id=:t"
                ),
                {"t": world[0].tenant_id},
            )
            == 1
        )


async def test_audio_crash_after_provider_start_never_retranscribes(session_factory):
    call = AsyncMock(
        side_effect=AudioTranscriptionError("audio_transcription_uncertain")
    )
    world, message, envelope, service, _, transcriber = await setup(
        session_factory, transcriber=call
    )
    await service.process(envelope)
    await service.process(envelope)
    row, replies = await state(session_factory, message)
    assert row["status"] == "UNCERTAIN"
    assert replies == 1
    assert transcriber.transcribe.await_count == 1
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='outbound.text' AND tenant_id=:t"
                ),
                {"t": world[0].tenant_id},
            )
            == 1
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.lead_prospects WHERE tenant_id=:t"),
                {"t": world[0].tenant_id},
            )
            == 0
        )


@pytest.mark.parametrize("change", ["handoff", "revoke"])
@pytest.mark.parametrize("when", ["before", "download", "transcription"])
async def test_audio_handoff_and_revocation_prevent_paid_work_or_reply(
    session_factory, change, when
):
    world, message, envelope, service, downloader, transcriber = await setup(
        session_factory
    )

    async def mutate():
        async with session_factory.begin() as session:
            if change == "handoff":
                await session.execute(
                    text(
                        "UPDATE public.conversations SET control_state='HUMAN_ACTIVE' WHERE id=:id"
                    ),
                    {"id": world[2]},
                )
            else:
                await session.execute(
                    text(
                        "UPDATE public.whatsapp_accounts SET status='inactive' WHERE id=:id"
                    ),
                    {"id": world[1]},
                )

    if when == "before":
        await mutate()
    elif when == "download":

        async def download(*args):
            await mutate()
            return SimpleNamespace(size_bytes=3, sha256="1" * 64)

        downloader.download.side_effect = download
    else:

        async def transcribe(*args):
            await mutate()
            return AudioTranscript("Quiero un agente", TRANSCRIPTION_MODEL)

        transcriber.transcribe.side_effect = transcribe
    await service.process(envelope)
    row, replies = await state(session_factory, message)
    assert replies == 0
    assert row["status"] == ("READY" if when == "transcription" else "CANCELLED")
    assert transcriber.transcribe.await_count == (1 if when == "transcription" else 0)


async def test_audio_preflight_defers_without_consuming_attempts(session_factory):
    world, message, envelope, service, _, _ = await setup(session_factory)
    preflight = AudioJobPreflight(session_factory)
    runner = DurableJobRunner(
        session_factory=session_factory, preflight=preflight.admit
    )
    from agents_factory.modules.audio_ingestion.capacity import AudioCapacityGuard

    async with AudioCapacityGuard(session_factory).hold(world[0].tenant_id):
        result = await runner.run(envelope=envelope, handler=service.process)
    assert result.status == "deferred"
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT attempt_count FROM public.outbox_jobs WHERE id=:j"),
                {"j": envelope.job_id},
            )
            == 0
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.job_attempts WHERE outbox_job_id=:j"),
                {"j": envelope.job_id},
            )
            == 0
        )


async def test_audio_two_workers_complete_only_current_lease(session_factory):
    started, release = asyncio.Event(), asyncio.Event()

    async def transcribe(*args):
        started.set()
        await release.wait()
        return AudioTranscript("Mensaje primero", TRANSCRIPTION_MODEL)

    world, message, envelope, service, _, transcriber = await setup(
        session_factory, transcriber=AsyncMock(side_effect=transcribe)
    )
    first = asyncio.create_task(service.process(envelope))
    await asyncio.wait_for(started.wait(), timeout=5)
    try:
        await operation(
            session_factory,
            world[0],
            lambda repo: repo.claim(
                message, uuid4(), datetime.now(UTC) + timedelta(seconds=121)
            ),
        )
    finally:
        release.set()
    await first
    row, replies = await state(session_factory, message)
    assert row["status"] == "UNCERTAIN" and row["transcript"] is None
    assert replies == 0
    assert transcriber.transcribe.await_count == 1


async def test_audio_wait_deadlines_release_following_text(session_factory):
    world, message, envelope, service, _, _ = await setup(session_factory)
    from apps.backend.tests.integration.test_lead_capture import inbound

    later, _ = await inbound(session_factory, world, "¿Y el precio?", sequence=2)
    now = datetime.now(UTC)
    assert await operation(
        session_factory, world[0], lambda repo: repo.blocked_until(world[2], 2, now)
    )
    assert (
        await operation(
            session_factory, world[0], lambda repo: repo.blocked_until(world[2], 1, now)
        )
        is None
    )
    assert (
        await operation(
            session_factory,
            world[0],
            lambda repo: repo.blocked_until(world[2], 2, now + timedelta(seconds=181)),
        )
        is None
    )
    service.clock = lambda: now + timedelta(seconds=181)
    await service.process(envelope)
    assert (await state(session_factory, message))[0]["status"] == "FAILED"
    assert (await state(session_factory, message))[1] == 1
