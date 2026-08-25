from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.ids import new_uuid7
from agents_factory.modules.tenants.models import Tenant
from agents_factory.modules.tenants.repository import TenantRepository
from agents_factory.modules.tenants.service import TenantService


async def _set_application_role(session: AsyncSession) -> None:
    await session.execute(text("SET LOCAL ROLE agents_factory_app"))


async def _seed_tenant(
    session_factory: async_sessionmaker[AsyncSession],
    tenant: Tenant,
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:id, :slug, :name, :status)"
            ),
            {
                "id": tenant.id,
                "slug": tenant.slug,
                "name": tenant.name,
                "status": tenant.status,
            },
        )


@pytest.mark.asyncio
async def test_repository_isolates_rows_and_transaction_local_context_resets(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a = Tenant.new(slug="tenant-a", name="Tenant A")
    tenant_b = Tenant.new(slug="tenant-b", name="Tenant B")
    await _seed_tenant(session_factory, tenant_a)
    await _seed_tenant(session_factory, tenant_b)

    async with session_factory.begin() as session:
        await _set_application_role(session)
        repository = TenantRepository(session)
        await repository.set_tenant_context(tenant_a.id)

        visible = await repository.list_visible()

        assert [tenant.id for tenant in visible] == [tenant_a.id]

    async with session_factory.begin() as session:
        await _set_application_role(session)
        visible_without_context = await TenantRepository(session).list_visible()

        assert visible_without_context == []


@pytest.mark.asyncio
async def test_repository_rejects_cross_tenant_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a_id = new_uuid7()
    tenant_b = Tenant.new(slug="tenant-b", name="Tenant B")

    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await _set_application_role(session)
            repository = TenantRepository(session)
            await repository.set_tenant_context(tenant_a_id)
            await repository.create(tenant_b)


@pytest.mark.asyncio
async def test_tenant_service_commits_business_audit_and_outbox_together(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    correlation_id = new_uuid7()
    actor_id = new_uuid7()

    async with session_factory.begin() as session:
        await _set_application_role(session)
        created = await TenantService(session).create_tenant(
            slug="atomic-tenant",
            name="Atomic Tenant",
            actor_id=actor_id,
            actor_type="platform_admin",
            correlation_id=correlation_id,
            idempotency_key="tenant:create:atomic-tenant",
        )

    assert created.id.version == 7
    async with session_factory.begin() as session:
        tenant_count = await session.scalar(
            text("SELECT count(*) FROM public.tenants WHERE id = :tenant_id"),
            {"tenant_id": created.id},
        )
        audit_count = await session.scalar(
            text(
                "SELECT count(*) FROM public.audit_events "
                "WHERE tenant_id = :tenant_id AND correlation_id = :correlation_id"
            ),
            {"tenant_id": created.id, "correlation_id": correlation_id},
        )
        outbox_count = await session.scalar(
            text(
                "SELECT count(*) FROM public.outbox_jobs "
                "WHERE tenant_id = :tenant_id AND idempotency_key = :idempotency_key"
            ),
            {
                "tenant_id": created.id,
                "idempotency_key": "tenant:create:atomic-tenant",
            },
        )

    assert (tenant_count, audit_count, outbox_count) == (1, 1, 1)


@pytest.mark.asyncio
async def test_tenant_service_rolls_back_all_rows_when_outbox_insert_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    correlation_id = new_uuid7()

    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            await _set_application_role(session)
            await TenantService(session).create_tenant(
                slug="rollback-tenant",
                name="Rollback Tenant",
                actor_id=None,
                actor_type="system",
                correlation_id=correlation_id,
                idempotency_key="",
            )

    async with session_factory.begin() as session:
        counts = (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.tenants WHERE slug = 'rollback-tenant'"
                )
            ),
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events "
                    "WHERE correlation_id = :correlation_id"
                ),
                {"correlation_id": correlation_id},
            ),
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE idempotency_key = ''"
                )
            ),
        )

    assert counts == (0, 0, 0)


@pytest.mark.asyncio
async def test_new_tenant_ids_are_uuid7(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _set_application_role(session)
        tenant = await TenantService(session).create_tenant(
            slug="uuid7-tenant",
            name="UUID7 Tenant",
            actor_id=None,
            actor_type="system",
            correlation_id=new_uuid7(),
            idempotency_key="tenant:create:uuid7-tenant",
        )

    assert isinstance(tenant.id, UUID)
    assert tenant.id.version == 7
