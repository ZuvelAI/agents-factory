from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.ids import new_uuid7
from agents_factory.common.queue import DurableJobRunner, JobEnvelope


async def _seed_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    max_attempts: int,
) -> JobEnvelope:
    tenant_id = new_uuid7()
    job_id = new_uuid7()
    aggregate_id = new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:tenant_id, :slug, 'Runner Tenant', 'active')"
            ),
            {"tenant_id": tenant_id, "slug": f"runner-{tenant_id.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.outbox_jobs "
                "(id, tenant_id, idempotency_key, topic, payload, status, "
                "available_at, max_attempts) VALUES (:id, :tenant_id, :key, "
                "'agent.turn', jsonb_build_object("
                "'aggregate_id', CAST(:aggregate_id AS text)), "
                "'queued', now(), :max_attempts)"
            ),
            {
                "id": job_id,
                "tenant_id": tenant_id,
                "key": f"runner-{job_id}",
                "aggregate_id": str(aggregate_id),
                "max_attempts": max_attempts,
            },
        )
    return JobEnvelope(
        job_id=job_id,
        tenant_id=tenant_id,
        kind="agent.turn",
        aggregate_id=aggregate_id,
    )


@pytest.mark.asyncio
async def test_bounded_failures_create_one_audited_dead_letter(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    envelope = await _seed_job(session_factory, max_attempts=2)
    runner = DurableJobRunner(session_factory=session_factory)

    async def fail(_envelope: JobEnvelope) -> None:
        raise RuntimeError("provider details must not be persisted")

    first = await runner.run(envelope=envelope, handler=fail)
    terminal = await runner.run(envelope=envelope, handler=fail)
    replay = await runner.run(envelope=envelope, handler=fail)

    assert first.status == "retry"
    assert first.attempt_number == 1
    assert terminal.status == "dead_letter"
    assert terminal.attempt_number == 2
    assert replay.status == "already_complete"
    async with session_factory.begin() as session:
        outbox = (
            await session.execute(
                text(
                    "SELECT status, attempt_count, last_error_code "
                    "FROM public.outbox_jobs WHERE id = :job_id"
                ),
                {"job_id": envelope.job_id},
            )
        ).one()
        attempts = (
            await session.execute(
                text(
                    "SELECT attempt_number, status, error_code "
                    "FROM public.job_attempts WHERE outbox_job_id = :job_id "
                    "ORDER BY attempt_number"
                ),
                {"job_id": envelope.job_id},
            )
        ).all()
        dead_letter_count = await session.scalar(
            text(
                "SELECT count(*) FROM public.dead_letter_jobs "
                "WHERE outbox_job_id = :job_id"
            ),
            {"job_id": envelope.job_id},
        )
        audit_count = await session.scalar(
            text(
                "SELECT count(*) FROM public.audit_events "
                "WHERE event_type = 'job.dead_lettered' "
                "AND entity_id = :job_id"
            ),
            {"job_id": envelope.job_id},
        )

    assert tuple(outbox) == ("dead_letter", 2, "runtime_error")
    assert [tuple(attempt) for attempt in attempts] == [
        (1, "failed", "runtime_error"),
        (2, "failed", "runtime_error"),
    ]
    assert dead_letter_count == 1
    assert audit_count == 1


@pytest.mark.asyncio
async def test_cancellation_is_recorded_before_redelivery_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    envelope = await _seed_job(session_factory, max_attempts=3)
    runner = DurableJobRunner(session_factory=session_factory)
    started = asyncio.Event()

    async def cancelled(_envelope: JobEnvelope) -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(runner.run(envelope=envelope, handler=cancelled))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    effects: set[UUID] = set()

    async def idempotent_success(current: JobEnvelope) -> None:
        effects.add(current.aggregate_id)

    result = await runner.run(envelope=envelope, handler=idempotent_success)

    assert result.status == "succeeded"
    assert result.attempt_number == 2
    assert effects == {envelope.aggregate_id}
    async with session_factory.begin() as session:
        attempts = (
            await session.execute(
                text(
                    "SELECT attempt_number, status, error_code "
                    "FROM public.job_attempts WHERE outbox_job_id = :job_id "
                    "ORDER BY attempt_number"
                ),
                {"job_id": envelope.job_id},
            )
        ).all()
    assert [tuple(attempt) for attempt in attempts] == [
        (1, "failed", "cancelled"),
        (2, "succeeded", None),
    ]
