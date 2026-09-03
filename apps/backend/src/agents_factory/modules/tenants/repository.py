from __future__ import annotations

from typing import Literal
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
                "(id,slug,name,legal_name,industry,timezone,locale,status,revision,"
                "created_at,updated_at) VALUES (:id,:slug,:name,:legal_name,"
                ":industry,:timezone,:locale,:status,:revision,:created_at,:updated_at) "
                "RETURNING id,slug,name,legal_name,industry,timezone,locale,status,"
                "revision,created_at,updated_at"
            ),
            {
                "id": tenant.id,
                "slug": tenant.slug,
                "name": tenant.name,
                "legal_name": tenant.legal_name,
                "industry": tenant.industry,
                "timezone": tenant.timezone,
                "locale": tenant.locale,
                "status": tenant.status,
                "revision": tenant.revision,
                "created_at": tenant.created_at,
                "updated_at": tenant.updated_at,
            },
        )
        return Tenant.from_mapping(result.mappings().one())

    async def get(self, tenant_id: UUID) -> Tenant | None:
        result = await self._session.execute(
            text(
                "SELECT id,slug,name,legal_name,industry,timezone,locale,status,"
                "revision,created_at,updated_at "
                "FROM public.tenants WHERE id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else Tenant.from_mapping(row)

    async def list_visible(self, *, limit: int = 100) -> list[Tenant]:
        result = await self._session.execute(
            text(
                "SELECT id,slug,name,legal_name,industry,timezone,locale,status,"
                "revision,created_at,updated_at FROM public.tenants "
                "ORDER BY created_at DESC,id DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        return [Tenant.from_mapping(row) for row in result.mappings()]

    async def update_profile(
        self,
        *,
        tenant_id: UUID,
        expected_revision: int,
        name: str,
        legal_name: str,
        industry: str,
        timezone: str,
        locale: Literal["es-CO", "en-US"],
    ) -> Tenant | None:
        result = await self._session.execute(
            text(
                "UPDATE public.tenants SET name=:name,legal_name=:legal_name,"
                "industry=:industry,timezone=:timezone,locale=:locale,"
                "revision=revision+1,updated_at=now() WHERE id=:tenant_id "
                "AND revision=:expected_revision RETURNING id,slug,name,legal_name,"
                "industry,timezone,locale,status,revision,created_at,updated_at"
            ),
            {
                "tenant_id": tenant_id,
                "expected_revision": expected_revision,
                "name": name,
                "legal_name": legal_name,
                "industry": industry,
                "timezone": timezone,
                "locale": locale,
            },
        )
        row = result.mappings().one_or_none()
        return None if row is None else Tenant.from_mapping(row)
