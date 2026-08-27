from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService


async def _create_tenant_and_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    slug: str,
) -> TenantContext:
    tenant_id = new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:id, :slug, :name, 'active')"
            ),
            {"id": tenant_id, "slug": slug, "name": slug},
        )
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=new_uuid7(),
    )


@pytest.mark.asyncio
async def test_enqueue_is_atomic_and_returns_existing_job_for_same_tenant_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await _create_tenant_and_context(session_factory, slug="tenant-a")

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = OutboxService(session)
        first = await service.enqueue(
            context=context,
            idempotency_key="stable-key",
            topic="tenant.created",
            payload={"version": 1},
        )
        repeated = await service.enqueue(
            context=context,
            idempotency_key="stable-key",
            topic="tenant.changed",
            payload={"version": 2},
        )

    assert repeated.id == first.id
    assert repeated.topic == "tenant.created"
    assert repeated.payload == {"version": 1}
    async with session_factory.begin() as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM public.outbox_jobs "
                "WHERE tenant_id = :tenant_id AND idempotency_key = 'stable-key'"
            ),
            {"tenant_id": context.tenant_id},
        )
    assert count == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_is_independent_across_tenants(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a = await _create_tenant_and_context(session_factory, slug="tenant-a")
    tenant_b = await _create_tenant_and_context(session_factory, slug="tenant-b")

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        first = await OutboxService(session).enqueue(
            context=tenant_a,
            idempotency_key="shared-key",
            topic="tenant.created",
            payload={"tenant": "a"},
        )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        second = await OutboxService(session).enqueue(
            context=tenant_b,
            idempotency_key="shared-key",
            topic="tenant.created",
            payload={"tenant": "b"},
        )

    assert first.id != second.id
    assert first.tenant_id == tenant_a.tenant_id
    assert second.tenant_id == tenant_b.tenant_id
