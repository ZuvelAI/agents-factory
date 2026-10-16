"""Publication provenance SQL. Caller owns the transaction and tenant context."""

from typing import Any
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context


class WorkspacePublicationRepository:
    def __init__(self, session: AsyncSession, context: TenantContext):
        self.session, self.context = session, context

    async def one(self, sql: str, **params: Any) -> dict[str, Any] | None:
        await set_tenant_context(self.session, self.context.tenant_id)
        result = await self.session.execute(
            text(sql), {"tenant": self.context.tenant_id, **params}
        )
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    async def lock_draft(self, agent_id: UUID) -> dict[str, Any] | None:
        return await self.one(
            "SELECT * FROM public.agent_configuration_drafts WHERE tenant_id=:tenant AND agent_instance_id=:agent FOR UPDATE",
            agent=agent_id,
        )

    async def candidate(
        self, agent_id: UUID, revision: int, code_digest: str
    ) -> dict[str, Any] | None:
        return await self.one(
            "SELECT * FROM public.workspace_agent_candidates WHERE tenant_id=:tenant AND agent_instance_id=:agent AND draft_revision=:revision AND code_digest=:code",
            agent=agent_id,
            revision=revision,
            code=code_digest,
        )

    async def source(self, version_id: UUID) -> dict[str, Any] | None:
        return await self.one(
            "SELECT 'AGENT_CONFIGURATION' AS source_kind, agent_instance_id, version_id, draft_revision AS revision, company_revision, source_digest, code_digest FROM public.workspace_agent_candidates WHERE tenant_id=:tenant AND version_id=:version UNION ALL SELECT 'LEGACY', v.agent_instance_id, c.version_id, c.onboarding_revision, NULL, NULL, c.code_digest FROM public.panel_agent_candidates c JOIN public.agent_spec_versions v ON (v.tenant_id,v.id)=(c.tenant_id,c.version_id) WHERE c.tenant_id=:tenant AND c.version_id=:version",
            version=version_id,
        )

    async def latest_version(self, agent_id: UUID) -> UUID | None:
        row = await self.one(
            "SELECT id FROM public.agent_spec_versions WHERE tenant_id=:tenant AND agent_instance_id=:agent ORDER BY version_number DESC LIMIT 1",
            agent=agent_id,
        )
        return row["id"] if row else None

    async def insert_candidate(
        self,
        *,
        agent_id: UUID,
        revision: int,
        company_revision: int,
        source_digest: str,
        code_digest: str,
        version_id: UUID,
    ) -> dict[str, Any]:
        row = await self.one(
            "INSERT INTO public.workspace_agent_candidates (tenant_id,agent_instance_id,draft_revision,company_revision,source_digest,code_digest,version_id) VALUES (:tenant,:agent,:revision,:company_revision,:source_digest,:code,:version) RETURNING *",
            agent=agent_id,
            revision=revision,
            company_revision=company_revision,
            source_digest=source_digest,
            code=code_digest,
            version=version_id,
        )
        assert row is not None
        return row
