from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit
from uuid import UUID

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.ids import new_uuid7
from agents_factory.common.locks import ConversationLockManager
from agents_factory.common.queue import DurableJobRunner, JobEnvelope


@pytest.fixture(scope="session")
def local_redis_url() -> str:
    redis_url = os.environ.get("TEST_REDIS_URL")
    if redis_url is None:
        pytest.fail("TEST_REDIS_URL is required for conversation lock tests")
    parsed = urlsplit(redis_url)
    if parsed.scheme != "redis" or parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        pytest.fail("conversation lock tests require isolated local Redis")
    return redis_url


@pytest_asyncio.fixture
async def redis_client(local_redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(local_redis_url, decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


async def _seed_conversation_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> JobEnvelope:
    envelope = JobEnvelope(
        job_id=new_uuid7(),
        tenant_id=new_uuid7(),
        kind="agent.turn",
        aggregate_id=new_uuid7(),
    )
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:tenant_id, :slug, 'Lock Tenant', 'active')"
            ),
            {
                "tenant_id": envelope.tenant_id,
                "slug": f"lock-{envelope.tenant_id.hex}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO public.outbox_jobs "
                "(id, tenant_id, idempotency_key, topic, payload, status, "
                "available_at) VALUES (:id, :tenant_id, :key, :topic, "
                ":payload, 'queued', now())"
            ).bindparams(bindparam("payload", type_=JSONB)),
            {
                "id": envelope.job_id,
                "tenant_id": envelope.tenant_id,
                "key": f"lock-{envelope.job_id}",
                "topic": envelope.kind,
                "payload": {"aggregate_id": str(envelope.aggregate_id)},
            },
        )
    return envelope


@pytest.mark.asyncio
async def test_same_conversation_is_serialized_beyond_the_initial_lease(
    redis_client: Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    envelope = await _seed_conversation_job(session_factory)
    manager = ConversationLockManager(
        redis_client,
        lease_seconds=0.20,
        acquire_timeout_seconds=2.0,
        poll_interval_seconds=0.01,
    )
    events: list[str] = []
    first_entered = asyncio.Event()
    runner = DurableJobRunner(
        session_factory=session_factory,
        conversation_locks=manager,
    )

    async def first(current: JobEnvelope) -> None:
        assert current == envelope
        events.append("first-enter")
        first_entered.set()
        await asyncio.sleep(0.45)
        events.append("first-exit")

    async def second() -> None:
        await first_entered.wait()
        async with manager.hold(
            tenant_id=envelope.tenant_id,
            conversation_id=envelope.aggregate_id,
        ):
            events.append("second-enter")
        events.append("second-exit")

    result, _ = await asyncio.gather(
        runner.run(envelope=envelope, handler=first),
        second(),
    )

    assert result.status == "succeeded"
    assert manager.key_for(envelope.tenant_id, envelope.aggregate_id) == (
        f"{envelope.tenant_id}:{envelope.aggregate_id}"
    )
    assert events == ["first-enter", "first-exit", "second-enter", "second-exit"]


@pytest.mark.asyncio
async def test_different_conversations_can_run_in_parallel(redis_client: Redis) -> None:
    tenant_id = new_uuid7()
    manager = ConversationLockManager(
        redis_client,
        lease_seconds=1.0,
        acquire_timeout_seconds=1.0,
        poll_interval_seconds=0.01,
    )
    both_entered = asyncio.Event()
    release = asyncio.Event()
    active = 0
    maximum_active = 0

    async def run(conversation_id: UUID) -> None:
        nonlocal active, maximum_active
        async with manager.hold(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        ):
            active += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                both_entered.set()
            await release.wait()
            active -= 1

    tasks = [
        asyncio.create_task(run(new_uuid7())),
        asyncio.create_task(run(new_uuid7())),
    ]
    await asyncio.wait_for(both_entered.wait(), timeout=1.0)
    release.set()
    await asyncio.gather(*tasks)

    assert maximum_active == 2
