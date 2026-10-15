from __future__ import annotations

from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.security import AdminPrincipal
from agents_factory.database import set_tenant_context
from agents_factory.modules.tenants.repository import TenantRepository
from .publication_service import publication_problem
from .workspace_models import (
    AgentConfigurationView,
    AgentOverview,
    AgentPage,
    AgentSummary,
    ChannelSummary,
    CompanyPage,
    CompanySummary,
    FeatureSummary,
)


def decode_cursor(cursor: str | None) -> UUID | None:
    if cursor is None:
        return None
    try:
        if len(cursor) > 64:
            raise ValueError()
        return UUID(b64decode(cursor, altchars=b"-_", validate=True).decode("ascii"))
    except (ValueError, UnicodeError, Base64Error):
        raise publication_problem(
            "invalid_workspace_cursor", "Cursor de lectura inválido.", 422
        ) from None


def encode_cursor(value: UUID) -> str:
    return urlsafe_b64encode(str(value).encode()).decode()


def configuration_view(config: dict[str, Any] | None) -> AgentConfigurationView | None:
    if config is None:
        return None
    # Whitelist structured data only. Never copy connector credentials or raw config.
    persona = config.get("persona") or {}
    context = config.get("approved_business_context") or {}
    return AgentConfigurationView(
        name=persona.get("business_name") or "Agente sin nombre",
        instructions=persona.get("instructions"),
        model=(config.get("model") or {}).get("model"),
        knowledge_summary=context.get("approved_summary"),
        capabilities=[
            FeatureSummary(
                key=c["name"],
                label=c["name"],
                availability="unknown",
                enabled=False,
                reason="Permiso declarado; disponibilidad de ejecución no verificada.",
            )
            for c in config.get("capabilities", [])
        ],
        integrations=[
            FeatureSummary(
                key=c["connector"],
                label=c["connector"],
                availability="unknown",
                enabled=False,
                reason="Referencia declarada; conexión no verificada.",
            )
            for c in config.get("connector_bindings", [])
        ],
    )


class AgentWorkspaceService:
    def __init__(self, session: AsyncSession, principal: AdminPrincipal):
        self.session, self.principal = session, principal

    async def list_companies(
        self, *, query: str | None = None, cursor: str | None = None, limit: int = 20
    ) -> CompanyPage:
        after = decode_cursor(cursor)
        # PlatformAdmin may list tenants; scoped agent reads still set tenant context.
        result = await self.session.execute(
            text(
                "SELECT id,name FROM public.tenants WHERE (CAST(:after AS uuid) IS NULL OR id>:after) "
                "AND (:query='' OR strpos(lower(name),lower(:query))>0) ORDER BY id LIMIT :limit"
            ),
            {"after": after, "query": (query or "").strip(), "limit": limit + 1},
        )
        rows = list(result.mappings())
        items = []
        for row in rows[:limit]:
            tenant = row["id"]
            await set_tenant_context(self.session, tenant)
            count = await self.session.scalar(
                text(
                    "SELECT count(*) FROM public.agent_instances WHERE tenant_id=:tenant"
                ),
                {"tenant": tenant},
            )
            agents = await self.list_agents(tenant_id=tenant, limit=3)
            items.append(
                CompanySummary(
                    id=tenant, name=row["name"], agent_count=count, agents=agents.items
                )
            )
        return CompanyPage(
            items=items,
            next_cursor=encode_cursor(rows[limit - 1]["id"])
            if len(rows) > limit
            else None,
        )

    async def _tenant(self, tenant_id: UUID) -> None:
        await set_tenant_context(self.session, tenant_id)
        if await TenantRepository(self.session).get(tenant_id) is None:
            raise publication_problem(
                "workspace_not_found", "Empresa o agente no encontrado.", 404
            )

    async def list_agents(
        self, *, tenant_id: UUID, cursor: str | None = None, limit: int = 20
    ) -> AgentPage:
        await self._tenant(tenant_id)
        after = decode_cursor(cursor)
        result = await self.session.execute(
            text(
                "SELECT id FROM public.agent_instances WHERE tenant_id=:tenant "
                "AND (CAST(:after AS uuid) IS NULL OR id>:after) ORDER BY id LIMIT :limit"
            ),
            {"tenant": tenant_id, "after": after, "limit": limit + 1},
        )
        ids = list(result.scalars())
        items = [
            (await self.get_agent(tenant_id=tenant_id, agent_id=i)).summary
            for i in ids[:limit]
        ]
        return AgentPage(
            items=items,
            next_cursor=encode_cursor(ids[limit - 1]) if len(ids) > limit else None,
        )

    async def get_agent(self, *, tenant_id: UUID, agent_id: UUID) -> AgentOverview:
        await self._tenant(tenant_id)
        exists = await self.session.scalar(
            text(
                "SELECT id FROM public.agent_instances WHERE tenant_id=:tenant AND id=:agent"
            ),
            {"tenant": tenant_id, "agent": agent_id},
        )
        if exists is None:
            raise publication_problem(
                "workspace_not_found", "Empresa o agente no encontrado.", 404
            )
        parameters = {"tenant": tenant_id, "agent": agent_id}
        published = (
            (
                await self.session.execute(
                    text(
                        "SELECT v.id,v.configuration,v.version_number FROM public.agent_spec_deployments d "
                        "JOIN public.agent_spec_versions v ON (v.tenant_id,v.agent_instance_id,v.id)=(d.tenant_id,d.agent_instance_id,d.version_id) "
                        "WHERE d.tenant_id=:tenant AND d.agent_instance_id=:agent AND v.state='PRODUCTION' "
                        "ORDER BY d.created_at DESC,d.id DESC LIMIT 1"
                    ),
                    parameters,
                )
            )
            .mappings()
            .one_or_none()
        )
        draft = (
            (
                await self.session.execute(
                    text(
                        "SELECT id,configuration FROM public.agent_spec_versions WHERE tenant_id=:tenant AND agent_instance_id=:agent "
                        "AND state<>'PRODUCTION' AND version_number>:number ORDER BY version_number DESC LIMIT 1"
                    ),
                    parameters
                    | {"number": published["version_number"] if published else 0},
                )
            )
            .mappings()
            .one_or_none()
        )
        rows = (
            await self.session.execute(
                text(
                    "SELECT a.id,a.status,a.health_status,a.display_phone_digits,a.last_health_checked_at "
                    "FROM public.account_agent_bindings b JOIN public.whatsapp_accounts a "
                    "ON (a.tenant_id,a.id)=(b.tenant_id,b.whatsapp_account_id) "
                    "WHERE b.tenant_id=:tenant AND b.agent_instance_id=:agent ORDER BY a.id"
                ),
                parameters,
            )
        ).mappings()
        channels = []
        for row in rows:
            checked = row["last_health_checked_at"]
            fresh = checked is not None and timedelta(0) <= datetime.now(
                timezone.utc
            ) - checked <= timedelta(minutes=15)
            state: Literal[
                "unknown", "connected", "disconnected", "review_required"
            ] = "unknown"
            if row["status"] != "active":
                state = "disconnected"
            elif fresh:
                if row["health_status"] == "HEALTHY":
                    state = "connected"
                elif row["health_status"] in ("REAUTH_REQUIRED", "ERROR"):
                    state = "review_required"
            channels.append(
                ChannelSummary(
                    account_id=row["id"],
                    display_number=("+" + row["display_phone_digits"])
                    if row["display_phone_digits"]
                    else None,
                    connection_status=state,
                    checked_at=checked,
                )
            )
        active_view = configuration_view(
            published["configuration"] if published else None
        )
        draft_view = configuration_view(draft["configuration"] if draft else None)
        display_view = active_view or draft_view
        return AgentOverview(
            summary=AgentSummary(
                id=agent_id,
                tenant_id=tenant_id,
                display_name=display_view.name
                if display_view
                else "Agente sin configurar",
                published_name=active_view.name if active_view else None,
                published_version_id=published["id"] if published else None,
                draft_version_id=draft["id"] if draft else None,
                has_pending_changes=draft is not None,
                execution_status="unknown" if channels else "unassigned",
                channel_accounts=channels,
            ),
            published=active_view,
            draft=draft_view,
            unavailable_sections=[
                "Edición independiente por agente: próxima entrega.",
                "Tono y propósito no disponibles como campos independientes en versiones heredadas.",
            ],
        )
