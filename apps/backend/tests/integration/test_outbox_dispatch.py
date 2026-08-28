from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.worker import WorkerSettings as AgentWorkerSettings
from knowledge_worker.worker import WorkerSettings as KnowledgeWorkerSettings
from outbound_worker.worker import WorkerSettings as OutboundWorkerSettings
from scheduler.worker import WorkerSettings as SchedulerWorkerSettings
from agents_factory.common.ids import new_uuid7
from agents_factory.common.queue import (
    JobEnvelope,
    OutboxDispatcher,
    json_job_deserializer,
    json_job_serializer,
)


async def _seed_outbox_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    kind: str = "whatsapp.inbound.received",
) -> tuple[UUID, UUID, UUID]:
    tenant_id = new_uuid7()
    job_id = new_uuid7()
    aggregate_id = new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:tenant_id, :slug, 'Queue Tenant', 'active')"
            ),
            {"tenant_id": tenant_id, "slug": f"queue-{tenant_id.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.outbox_jobs "
                "(id, tenant_id, idempotency_key, topic, payload, status, "
                "available_at) VALUES (:id, :tenant_id, :key, :topic, "
                "jsonb_build_object("
                "'aggregate_id', CAST(:aggregate_id AS text)), "
                "'pending', now())"
            ),
            {
                "id": job_id,
                "tenant_id": tenant_id,
                "key": f"queue-{job_id}",
                "topic": kind,
                "aggregate_id": str(aggregate_id),
            },
        )
    return tenant_id, job_id, aggregate_id


class _UncertainOnceQueue:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self.seen_job_ids: set[str] = set()
        self.calls: list[dict[str, object]] = []
        self.committed_statuses: list[str] = []
        self._raise_after_first_accept = True

    async def enqueue_job(
        self,
        function_name: str,
        envelope: Mapping[str, object],
        *,
        _job_id: str,
        _queue_name: str,
    ) -> object | None:
        async with self._session_factory.begin() as session:
            status = await session.scalar(
                text("SELECT status FROM public.outbox_jobs WHERE id = :job_id"),
                {"job_id": UUID(_job_id)},
            )
        assert isinstance(status, str)
        self.committed_statuses.append(status)
        self.calls.append(
            {
                "function_name": function_name,
                "envelope": dict(envelope),
                "job_id": _job_id,
                "queue_name": _queue_name,
            }
        )
        duplicate = _job_id in self.seen_job_ids
        self.seen_job_ids.add(_job_id)
        if self._raise_after_first_accept:
            self._raise_after_first_accept = False
            raise ConnectionError("queue result was uncertain")
        return None if duplicate else object()


@pytest.mark.asyncio
async def test_dispatch_commits_claim_before_enqueue_and_recovers_uncertain_result(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, job_id, aggregate_id = await _seed_outbox_job(session_factory)
    queue = _UncertainOnceQueue(session_factory)
    dispatcher = OutboxDispatcher(
        session_factory=session_factory,
        queue=queue,
        queue_by_kind={"whatsapp.inbound.received": "agent"},
    )

    first = await dispatcher.dispatch_once(limit=1)
    second = await dispatcher.dispatch_once(limit=1)

    assert first.failed == 1
    assert second.dispatched == 0
    assert second.already_enqueued == 1
    assert queue.committed_statuses == ["dispatching", "dispatching"]
    assert len(queue.seen_job_ids) == 1
    assert [call["job_id"] for call in queue.calls] == [str(job_id), str(job_id)]
    assert queue.calls[-1] == {
        "function_name": "process_job",
        "envelope": {
            "schema_version": 1,
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "kind": "whatsapp.inbound.received",
            "aggregate_id": str(aggregate_id),
        },
        "job_id": str(job_id),
        "queue_name": "agent",
    }
    async with session_factory.begin() as session:
        state = (
            await session.execute(
                text(
                    "SELECT status, dispatched_at IS NOT NULL, "
                    "dispatch_lease_id IS NULL FROM public.outbox_jobs "
                    "WHERE id = :job_id"
                ),
                {"job_id": job_id},
            )
        ).one()
    assert tuple(state) == ("queued", True, True)


def test_job_envelope_uses_strict_json_and_all_workers_share_it() -> None:
    envelope = JobEnvelope(
        job_id=new_uuid7(),
        tenant_id=new_uuid7(),
        kind="agent.turn",
        aggregate_id=new_uuid7(),
    )
    arq_job = {
        "t": 1,
        "f": "process_job",
        "a": [envelope.to_arq_payload()],
        "k": {},
        "et": 1787788800000,
    }

    encoded = json_job_serializer(arq_job)

    assert encoded.startswith(b'{"a"')
    assert json_job_deserializer(encoded) == arq_job
    assert AgentWorkerSettings.queue_name == "agent"
    assert KnowledgeWorkerSettings.queue_name == "knowledge"
    assert OutboundWorkerSettings.queue_name == "outbound"
    assert SchedulerWorkerSettings.queue_name == "scheduler"
    for settings in (
        AgentWorkerSettings,
        KnowledgeWorkerSettings,
        OutboundWorkerSettings,
        SchedulerWorkerSettings,
    ):
        assert settings.job_serializer is json_job_serializer
        assert settings.job_deserializer is json_job_deserializer
        assert settings.functions
