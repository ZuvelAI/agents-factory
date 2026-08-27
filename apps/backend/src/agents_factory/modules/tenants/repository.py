from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.database import set_tenant_context
from agents_factory.modules.tenants.models import Tenant


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_tenant_context(self, tenant_id: UUID) -> None:
        await set_tenant_context(self._session, tenant_id)

    async def create(self, tenant: Tenant) -> Tenant:
        result = await self._session.execute(
            text(
                "INSERT INTO public.tenants "
                "(id, slug, name, status, created_at, updated_at) "
                "VALUES (:id, :slug, :name, :status, :created_at, :updated_at) "
                "RETURNING id, slug, name, status, created_at, updated_at"
            ),
            {
                "id": tenant.id,
                "slug": tenant.slug,
                "name": tenant.name,
                "status": tenant.status,
                "created_at": tenant.created_at,
                "updated_at": tenant.updated_at,
            },
        )
        return Tenant.from_mapping(result.mappings().one())

    async def get(self, tenant_id: UUID) -> Tenant | None:
        result = await self._session.execute(
            text(
                "SELECT id, slug, name, status, created_at, updated_at "
                "FROM public.tenants WHERE id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else Tenant.from_mapping(row)

    async def list_visible(self) -> list[Tenant]:
        result = await self._session.execute(
            text(
                "SELECT id, slug, name, status, created_at, updated_at "
                "FROM public.tenants ORDER BY id"
            )
        )
        return [Tenant.from_mapping(row) for row in result.mappings()]
