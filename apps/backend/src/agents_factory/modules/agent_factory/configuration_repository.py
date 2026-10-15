"""Tenant-scoped editable configuration storage. Transaction ownership is external."""

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context


class ConfigurationRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def _query(
        self,
        statement: str,
        parameters: dict[str, Any] | None = None,
        *,
        json_fields: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        await set_tenant_context(self._session, self._context.tenant_id)
        query = text(statement)
        for name in json_fields:
            query = query.bindparams(bindparam(name, type_=JSONB))
        result = await self._session.execute(
            query, {"tenant": self._context.tenant_id, **(parameters or {})}
        )
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    async def read_company(self) -> dict[str, Any] | None:
        return await self._query(
            "SELECT * FROM public.company_profiles WHERE tenant_id=:tenant"
        )

    async def lock_legacy(self) -> dict[str, Any] | None:
        return await self._query(
            "SELECT revision,configuration FROM public.tenant_onboarding_configs "
            "WHERE tenant_id=:tenant FOR UPDATE"
        )

    async def legacy_instance(self, revision: int) -> UUID | None:
        row = await self._query(
            "SELECT CASE WHEN count(DISTINCT v.agent_instance_id)=1 "
            "THEN (array_agg(DISTINCT v.agent_instance_id))[1] ELSE NULL END AS agent "
            "FROM public.panel_agent_candidates c JOIN public.agent_spec_versions v "
            "ON (v.tenant_id,v.id)=(c.tenant_id,c.version_id) "
            "WHERE c.tenant_id=:tenant AND c.onboarding_revision=:revision",
            {"revision": revision},
        )
        return row["agent"] if row else None

    async def lock_company(self) -> dict[str, Any] | None:
        return await self._query(
            "SELECT * FROM public.company_profiles WHERE tenant_id=:tenant FOR UPDATE"
        )

    async def update_company_name(self, name: str) -> None:
        await self._query(
            "UPDATE public.tenants SET name=:name,updated_at=now() WHERE id=:tenant RETURNING id",
            {"name": name},
        )

    async def refresh_company(
        self,
        *,
        agent_id: UUID,
        expected_revision: int,
        company_revision: int,
        company_snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        return await self._query(
            "UPDATE public.agent_configuration_drafts SET company_snapshot=:snapshot, "
            "company_revision=:company_revision,revision=revision+1,updated_at=now() "
            "WHERE tenant_id=:tenant AND agent_instance_id=:agent AND revision=:revision RETURNING *",
            {
                "agent": agent_id,
                "revision": expected_revision,
                "company_revision": company_revision,
                "snapshot": company_snapshot,
            },
            json_fields=("snapshot",),
        )

    async def insert_company(
        self, configuration: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self._query(
            "INSERT INTO public.company_profiles(tenant_id,revision,configuration) "
            "VALUES(:tenant,1,:configuration) ON CONFLICT(tenant_id) DO NOTHING RETURNING *",
            {"configuration": configuration},
            json_fields=("configuration",),
        )

    async def update_company(
        self, *, expected_revision: int, configuration: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self._query(
            "UPDATE public.company_profiles SET configuration=:configuration, "
            "revision=revision+1,updated_at=now() WHERE tenant_id=:tenant "
            "AND revision=:revision RETURNING *",
            {"configuration": configuration, "revision": expected_revision},
            json_fields=("configuration",),
        )

    async def read_draft(self, agent_id: UUID) -> dict[str, Any] | None:
        return await self._query(
            "SELECT * FROM public.agent_configuration_drafts "
            "WHERE tenant_id=:tenant AND agent_instance_id=:agent",
            {"agent": agent_id},
        )

    async def insert_draft(
        self,
        *,
        agent_id: UUID,
        company_revision: int,
        company_snapshot: dict[str, Any],
        configuration: dict[str, Any],
        provenance: dict[str, Any],
    ) -> dict[str, Any] | None:
        return await self._query(
            "INSERT INTO public.agent_configuration_drafts(tenant_id,agent_instance_id,"
            "revision,company_revision,company_snapshot,configuration,provenance) "
            "VALUES(:tenant,:agent,1,:company_revision,:company_snapshot,:configuration,:provenance) "
            "ON CONFLICT(tenant_id,agent_instance_id) DO NOTHING RETURNING *",
            {
                "agent": agent_id,
                "company_revision": company_revision,
                "company_snapshot": company_snapshot,
                "configuration": configuration,
                "provenance": provenance,
            },
            json_fields=("company_snapshot", "configuration", "provenance"),
        )

    async def update_draft(
        self, *, agent_id: UUID, expected_revision: int, configuration: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self._query(
            "UPDATE public.agent_configuration_drafts SET configuration=:configuration, "
            "revision=revision+1,updated_at=now() WHERE tenant_id=:tenant "
            "AND agent_instance_id=:agent AND revision=:revision RETURNING *",
            {
                "agent": agent_id,
                "revision": expected_revision,
                "configuration": configuration,
            },
            json_fields=("configuration",),
        )
