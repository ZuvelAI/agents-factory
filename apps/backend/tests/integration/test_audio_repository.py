from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agents_factory.modules.audio_ingestion.models import AudioTranscript
from agents_factory.modules.audio_ingestion.repository import AudioRepository
from agents_factory.modules.audio_ingestion.capacity import (
    AudioCapacityGuard,
    AudioCapacityLost,
)
from apps.backend.tests.integration.audio_fixtures import audio_world


async def operation(factory, context, callback):
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        return await callback(AudioRepository(session, context))


async def test_audio_claim_is_tenant_scoped_and_deduplicated(session_factory):
    world, message = await audio_world(session_factory)
    other, other_message = await audio_world(session_factory)

    async def run(context, fn):
        return await operation(session_factory, context, fn)

    ident = await run(world[0], lambda repo: repo.enqueue(message))
    assert await run(world[0], lambda repo: repo.enqueue(message)) == ident
    assert await run(other[0], lambda repo: repo.enqueue(other_message)) != ident
    with pytest.raises(ValueError):
        await run(other[0], lambda repo: repo.enqueue(message))
    claim = await run(
        world[0], lambda repo: repo.claim(message, uuid4(), datetime.now(UTC))
    )
    assert claim.source.account_id == world[1]
    assert claim.source.media_id == "12345678"
    assert (
        await run(
            world[0], lambda repo: repo.claim(message, uuid4(), datetime.now(UTC))
        )
        is None
    )
    async with session_factory.begin() as s:
        assert (
            await s.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='whatsapp.audio.transcribe'"
                )
            )
            == 2
        )


async def test_audio_ready_is_immutable(session_factory):
    world, message = await audio_world(session_factory)

    async def run(fn):
        return await operation(session_factory, world[0], fn)

    await run(lambda repo: repo.enqueue(message))
    now = datetime.now(UTC)
    claim = await run(lambda repo: repo.claim(message, uuid4(), now))
    assert await run(lambda repo: repo.start_provider(claim, now))
    transcript = AudioTranscript(
        text="Quiero un agente", model="gpt-4o-mini-transcribe-2025-12-15"
    )
    assert await run(lambda repo: repo.complete(claim, transcript))
    assert not await run(
        lambda repo: repo.complete(
            claim, AudioTranscript(text="Otro texto", model=transcript.model)
        )
    )
    assert (await run(lambda repo: repo.read_ready((message,))))[
        message
    ].text == "Quiero un agente"
    async with session_factory.begin() as s:
        assert (
            await s.scalar(
                text("SELECT count(*) FROM public.outbox_jobs WHERE topic='agent.turn'")
            )
            == 1
        )
        await s.execute(text("SET LOCAL ROLE agents_factory_app"))
        from agents_factory.database import set_tenant_context

        await set_tenant_context(s, world[0].tenant_id)
        with pytest.raises(DBAPIError) as denied:
            async with s.begin_nested():
                await s.execute(
                    text(
                        "UPDATE public.whatsapp_audio_transcriptions SET transcript='replacement' WHERE inbound_message_id=:m"
                    ),
                    {"m": message},
                )
        assert denied.value.orig.sqlstate == "55000"


async def test_audio_expired_provider_claim_becomes_uncertain(session_factory):
    world, message = await audio_world(session_factory)

    async def run(fn):
        return await operation(session_factory, world[0], fn)

    await run(lambda repo: repo.enqueue(message))
    now = datetime.now(UTC)
    claim = await run(lambda repo: repo.claim(message, uuid4(), now))
    assert await run(lambda repo: repo.start_provider(claim, now))
    assert (
        await run(
            lambda repo: repo.claim(message, uuid4(), now + timedelta(seconds=121))
        )
        is None
    )
    assert not await run(lambda repo: repo.start_provider(claim, now))
    async with session_factory.begin() as s:
        assert (
            await s.scalar(
                text(
                    "SELECT status FROM public.whatsapp_audio_transcriptions WHERE inbound_message_id=:id"
                ),
                {"id": message},
            )
            == "UNCERTAIN"
        )


async def test_audio_expired_queue_and_preflight_have_bounded_deadlines(
    session_factory,
):
    world, message = await audio_world(session_factory)

    async def run(fn):
        return await operation(session_factory, world[0], fn)

    await run(lambda repo: repo.enqueue(message))
    async with session_factory.begin() as s:
        created = await s.scalar(
            text(
                "SELECT created_at FROM public.whatsapp_audio_transcriptions WHERE inbound_message_id=:id"
            ),
            {"id": message},
        )
    assert (
        await run(
            lambda repo: repo.claim(message, uuid4(), created + timedelta(seconds=181))
        )
        is None
    )
    async with session_factory.begin() as s:
        assert (
            await s.scalar(
                text(
                    "SELECT status FROM public.whatsapp_audio_transcriptions WHERE inbound_message_id=:id"
                ),
                {"id": message},
            )
            == "FAILED"
        )


async def test_audio_slots_bound_two_global_one_tenant(session_factory):
    guard = AudioCapacityGuard(session_factory)
    tenant, other, third = uuid4(), uuid4(), uuid4()
    async with guard.hold(tenant) as first:
        assert first is not None
        async with guard.hold(tenant) as duplicate:
            assert duplicate is None
        async with guard.hold(other) as second:
            assert second is not None
            async with guard.hold(third) as rejected:
                assert rejected is None
        await first.check()
    async with guard.hold(third) as after:
        assert after is not None


async def test_audio_capacity_detects_lost_session_before_more_external_work(
    session_factory,
):
    guard = AudioCapacityGuard(session_factory)
    with pytest.raises(AudioCapacityLost):
        async with guard.hold(uuid4()) as lease:
            assert lease is not None
            await lease.connection.invalidate()
            await lease.connection.rollback()
            # A reconnect can execute SELECT 1 but no longer owns the old slots.
            await lease.check()


async def test_audio_phase_cannot_be_reset_after_provider_started(session_factory):
    world, message = await audio_world(session_factory)

    async def run(fn):
        return await operation(session_factory, world[0], fn)

    await run(lambda repo: repo.enqueue(message))
    claim = await run(lambda repo: repo.claim(message, uuid4(), datetime.now(UTC)))
    assert await run(lambda repo: repo.start_provider(claim, datetime.now(UTC)))
    async with session_factory.begin() as s:
        await s.execute(text("SET LOCAL ROLE agents_factory_app"))
        from agents_factory.database import set_tenant_context

        await set_tenant_context(s, world[0].tenant_id)
        with pytest.raises(DBAPIError) as denied:
            async with s.begin_nested():
                await s.execute(
                    text(
                        "UPDATE public.whatsapp_audio_transcriptions SET phase='PREFLIGHT' WHERE inbound_message_id=:m"
                    ),
                    {"m": message},
                )
        assert denied.value.orig.sqlstate == "55000"


async def test_audio_preflight_renew_and_reclaim_never_extend_first_deadline(
    session_factory,
):
    world, message = await audio_world(session_factory)

    async def run(fn):
        return await operation(session_factory, world[0], fn)

    await run(lambda repo: repo.enqueue(message))
    now = datetime.now(UTC)
    first = await run(lambda repo: repo.claim(message, uuid4(), now))
    assert await run(lambda repo: repo.renew(first, now + timedelta(seconds=40)))
    assert (
        await run(
            lambda repo: repo.claim(message, uuid4(), now + timedelta(seconds=46))
        )
        is None
    )
    replacement = await run(
        lambda repo: repo.claim(message, uuid4(), now + timedelta(seconds=86))
    )
    assert replacement.deadline == first.deadline
    assert replacement.lease_id != first.lease_id
    assert not await run(
        lambda repo: repo.start_provider(first, now + timedelta(seconds=87))
    )
    assert (
        await run(
            lambda repo: repo.claim(message, uuid4(), now + timedelta(seconds=121))
        )
        is None
    )


async def test_audio_finish_and_barrier_respect_scope_and_terminal_state(
    session_factory,
):
    world, message = await audio_world(session_factory)

    async def run(fn):
        return await operation(session_factory, world[0], fn)

    await run(lambda repo: repo.enqueue(message))
    now = datetime.now(UTC)
    assert await run(lambda repo: repo.blocked_until(world[2], 2, now)) is not None
    assert await run(lambda repo: repo.blocked_until(world[2], 1, now)) is None
    claim = await run(lambda repo: repo.claim(message, uuid4(), now))
    assert await run(
        lambda repo: repo.finish(claim, "CANCELLED", "audio_human_control")
    )
    assert not await run(lambda repo: repo.finish(claim, "FAILED", "audio_failed"))
    assert await run(lambda repo: repo.blocked_until(world[2], 2, now)) is None
