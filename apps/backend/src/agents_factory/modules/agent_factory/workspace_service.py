"""Workspace use cases: authorize scope, read stored facts, return safe projections.

GET operations never compile, publish, connect providers or create audit entries.
SQL belongs in WorkspaceRepository; pure presentation rules in workspace_projection.
"""

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal
from agents_factory.database import set_tenant_context
from agents_factory.modules.tenants.repository import TenantRepository
from .repository import AgentSpecRepository
from .publication_service import publication_problem
from .workspace_cursor import decode_cursor, encode_cursor
from .workspace_models import (
    AgentOverview,
    AgentPage,
    AgentSummary,
    ChannelVersionView,
    CompanyPage,
    CompanySummary,
    AccountPage,
    CompanyOption,
    CompanyOptionPage,
)
from .workspace_projection import (
    agent_summary,
    channel_summary,
    configuration_view,
    editable_configuration_view,
)
from .configuration_repository import ConfigurationRepository
from .workspace_repository import WorkspaceRepository


class AgentWorkspaceService:
    def __init__(self, session: AsyncSession, principal: AdminPrincipal):
        self.session, self.principal = session, principal
        self.repository = WorkspaceRepository(session)

    async def _tenant(self, tenant_id: UUID) -> str:
        await set_tenant_context(self.session, tenant_id)
        tenant = await TenantRepository(self.session).get(tenant_id)
        if tenant is None:
            raise publication_problem(
                "workspace_not_found", "Empresa o agente no encontrado.", 404
            )
        return tenant.name

    async def list_companies(
        self, *, query: str | None = None, cursor: str | None = None, limit: int = 20
    ) -> CompanyPage:
        rows = await self.repository.companies(
            query=(query or "").strip(), after=decode_cursor(cursor), limit=limit + 1
        )
        items = []
        for row in rows[:limit]:
            await set_tenant_context(self.session, row["id"])
            summaries = await self.repository.agent_summaries(
                tenant=row["id"], after=None, limit=3
            )
            items.append(
                CompanySummary(
                    id=row["id"],
                    name=row["name"],
                    agent_count=summaries[0]["agent_count"] if summaries else 0,
                    agents=[agent_summary(r) for r in summaries],
                )
            )
        return CompanyPage(
            items=items,
            next_cursor=encode_cursor(rows[limit - 1]["id"])
            if len(rows) > limit
            else None,
        )

    async def list_agents(
        self, *, tenant_id: UUID, cursor: str | None = None, limit: int = 20
    ) -> AgentPage:
        name = await self._tenant(tenant_id)
        rows = await self.repository.agent_summaries(
            tenant=tenant_id, after=decode_cursor(cursor), limit=limit + 1
        )
        return AgentPage(
            items=[agent_summary(r) for r in rows[:limit]],
            company_name=name,
            next_cursor=encode_cursor(rows[limit - 1]["id"])
            if len(rows) > limit
            else None,
        )

    async def list_company_options(
        self, *, cursor: str | None = None, limit: int = 20
    ) -> CompanyOptionPage:
        rows = await self.repository.companies(
            query="", after=decode_cursor(cursor), limit=limit + 1
        )
        return CompanyOptionPage(
            items=[CompanyOption(id=r["id"], name=r["name"]) for r in rows[:limit]],
            next_cursor=encode_cursor(rows[limit - 1]["id"])
            if len(rows) > limit
            else None,
        )

    async def list_accounts(
        self, *, tenant_id: UUID, cursor: str | None = None, limit: int = 20
    ) -> AccountPage:
        await self._tenant(tenant_id)
        rows = await self.repository.accounts(
            tenant_id, decode_cursor(cursor), limit + 1
        )
        return AccountPage(
            items=[channel_summary(r) for r in rows[:limit]],
            next_cursor=encode_cursor(rows[limit - 1]["id"])
            if len(rows) > limit
            else None,
        )

    async def get_agent(self, *, tenant_id: UUID, agent_id: UUID) -> AgentOverview:
        await self._tenant(tenant_id)
        context = TenantContext(
            tenant_id=tenant_id,
            actor_id=self.principal.user_id,
            actor_type="platform_admin",
            correlation_id=self.principal.session_id,
        )
        if (
            await AgentSpecRepository(self.session, context).get_instance(agent_id)
            is None
        ):
            raise publication_problem(
                "workspace_not_found", "Empresa o agente no encontrado.", 404
            )
        published = await self.repository.latest_publication(tenant_id, agent_id)
        draft = await self.repository.latest_candidate(
            tenant_id, agent_id, published["version_number"] if published else 0
        )
        rows = await self.repository.channels(tenant_id, agent_id)
        channels = [channel_summary(row) for row in rows]
        versions: dict[UUID, ChannelVersionView] = {}
        for row in rows:
            versions.setdefault(
                row["version_id"],
                ChannelVersionView(
                    version_id=row["version_id"],
                    account_ids=[],
                    configuration=configuration_view(row["configuration"]),
                ),
            ).account_ids.append(row["id"])
        active = configuration_view(published["configuration"] if published else None)
        candidate = configuration_view(draft["configuration"] if draft else None)
        editable = await ConfigurationRepository(self.session, context).read_draft(
            agent_id
        )
        if editable is not None:
            candidate = editable_configuration_view(editable["configuration"])
        display = active or candidate
        summary = AgentSummary(
            id=agent_id,
            tenant_id=tenant_id,
            display_name=display.name if display else "Agente sin configurar",
            published_name=active.name if active else None,
            published_version_id=published["id"] if published else None,
            draft_version_id=draft["id"] if draft else None,
            has_pending_changes=draft is not None or editable is not None,
            purpose=candidate.purpose if candidate else None,
            execution_status="unknown" if channels else "unassigned",
            channel_accounts=channels,
        )
        return AgentOverview(
            summary=summary,
            published=active,
            draft=candidate,
            channel_versions=list(versions.values()),
            editable_revision=editable["revision"] if editable else None,
            unavailable_sections=[
                "Publicar y probar el nuevo borrador: siguiente entrega.",
                "Tono y propósito no disponibles como campos independientes en versiones heredadas.",
            ],
        )
