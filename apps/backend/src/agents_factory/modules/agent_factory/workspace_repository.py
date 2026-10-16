"""Read-only workspace queries. No lifecycle transitions or credential projections."""

from typing import Any
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


AGENT_SUMMARIES = """
SELECT i.id,i.tenant_id,count(*) OVER() AS agent_count,p.id AS published_id,p.name AS published_name,
       d.id AS draft_id,coalesce(e.configuration#>>'{agent,agent_name}',d.name) AS draft_name,
       e.revision AS editable_revision,e.configuration->>'purpose' AS purpose,
       e.company_revision AS editable_company_revision,cp.revision AS current_company_revision,
       pc.draft_revision AS published_draft_revision,pc.company_revision AS published_company_revision,
       coalesce(ch.items,'[]'::jsonb) AS channels
FROM public.agent_instances i
LEFT JOIN public.agent_configuration_drafts e ON (e.tenant_id,e.agent_instance_id)=(i.tenant_id,i.id)
LEFT JOIN LATERAL (
  SELECT v.id,v.version_number,v.configuration#>>'{persona,business_name}' AS name
  FROM public.agent_spec_deployments deployment
  JOIN public.agent_spec_versions v ON (v.tenant_id,v.agent_instance_id,v.id)=
       (deployment.tenant_id,deployment.agent_instance_id,deployment.version_id)
  WHERE deployment.tenant_id=i.tenant_id AND deployment.agent_instance_id=i.id
    AND v.state='PRODUCTION'
  ORDER BY deployment.created_at DESC,deployment.id DESC LIMIT 1
) p ON true
LEFT JOIN public.company_profiles cp ON cp.tenant_id=i.tenant_id
LEFT JOIN public.workspace_agent_candidates pc ON
  (pc.tenant_id,pc.agent_instance_id,pc.version_id)=(i.tenant_id,i.id,p.id)
LEFT JOIN LATERAL (
  SELECT v.id,v.configuration#>>'{persona,business_name}' AS name
  FROM public.agent_spec_versions v
  WHERE v.tenant_id=i.tenant_id AND v.agent_instance_id=i.id AND v.state<>'PRODUCTION'
    AND v.version_number>coalesce(p.version_number,0)
  ORDER BY v.version_number DESC LIMIT 1
) d ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object('id',a.id,'status',a.status,
    'health_status',a.health_status,'display_phone_digits',a.display_phone_digits,
    'last_health_checked_at',a.last_health_checked_at,'version_id',b.version_id)
    ORDER BY a.id) AS items
  FROM public.account_agent_bindings b JOIN public.whatsapp_accounts a
    ON (a.tenant_id,a.id)=(b.tenant_id,b.whatsapp_account_id)
  WHERE b.tenant_id=i.tenant_id AND b.agent_instance_id=i.id
) ch ON true
WHERE i.tenant_id=:tenant AND (CAST(:after AS uuid) IS NULL OR i.id>:after)
ORDER BY i.id LIMIT :limit
"""


class WorkspaceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def companies(
        self, *, query: str, after: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        rows = await self.session.execute(
            text(
                "SELECT t.id,t.name "
                "FROM public.tenants t WHERE (CAST(:after AS uuid) IS NULL OR t.id>:after) "
                "AND (:query='' OR strpos(lower(t.name),lower(:query))>0) ORDER BY t.id LIMIT :limit"
            ),
            {"after": after, "query": query, "limit": limit},
        )
        return [dict(r) for r in rows.mappings()]

    async def agent_summaries(
        self, *, tenant: UUID, after: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        rows = await self.session.execute(
            text(AGENT_SUMMARIES), {"tenant": tenant, "after": after, "limit": limit}
        )
        return [dict(r) for r in rows.mappings()]

    async def latest_publication(
        self, tenant: UUID, agent: UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT v.id,v.configuration,v.version_number, "
                        "pc.draft_revision AS published_draft_revision,pc.company_revision AS published_company_revision, "
                        "cp.revision AS current_company_revision FROM public.agent_spec_deployments d "
                        "JOIN public.agent_spec_versions v ON (v.tenant_id,v.agent_instance_id,v.id)=(d.tenant_id,d.agent_instance_id,d.version_id) "
                        "LEFT JOIN public.workspace_agent_candidates pc ON (pc.tenant_id,pc.agent_instance_id,pc.version_id)=(v.tenant_id,v.agent_instance_id,v.id) "
                        "LEFT JOIN public.company_profiles cp ON cp.tenant_id=v.tenant_id "
                        "WHERE d.tenant_id=:tenant AND d.agent_instance_id=:agent AND v.state='PRODUCTION' "
                        "ORDER BY d.created_at DESC,d.id DESC LIMIT 1"
                    ),
                    {"tenant": tenant, "agent": agent},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def latest_candidate(
        self, tenant: UUID, agent: UUID, after_version: int
    ) -> dict[str, Any] | None:
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT id,configuration FROM public.agent_spec_versions WHERE tenant_id=:tenant AND agent_instance_id=:agent "
                        "AND state<>'PRODUCTION' AND version_number>:number ORDER BY version_number DESC LIMIT 1"
                    ),
                    {"tenant": tenant, "agent": agent, "number": after_version},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def channels(self, tenant: UUID, agent: UUID) -> list[dict[str, Any]]:
        rows = await self.session.execute(
            text(
                "SELECT a.id,a.status,a.health_status,a.display_phone_digits,a.last_health_checked_at,b.version_id,v.configuration "
                "FROM public.account_agent_bindings b JOIN public.whatsapp_accounts a ON (a.tenant_id,a.id)=(b.tenant_id,b.whatsapp_account_id) "
                "JOIN public.agent_spec_versions v ON (v.tenant_id,v.agent_instance_id,v.id)=(b.tenant_id,b.agent_instance_id,b.version_id) "
                "WHERE b.tenant_id=:tenant AND b.agent_instance_id=:agent ORDER BY a.id"
            ),
            {"tenant": tenant, "agent": agent},
        )
        return [dict(r) for r in rows.mappings()]

    async def accounts(
        self, tenant: UUID, after: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        rows = await self.session.execute(
            text(
                "SELECT a.id,a.status,a.health_status,a.display_phone_digits,a.last_health_checked_at,b.version_id "
                "FROM public.whatsapp_accounts a LEFT JOIN public.account_agent_bindings b "
                "ON (b.tenant_id,b.whatsapp_account_id)=(a.tenant_id,a.id) "
                "WHERE a.tenant_id=:tenant AND (CAST(:after AS uuid) IS NULL OR a.id>:after) ORDER BY a.id LIMIT :limit"
            ),
            {"tenant": tenant, "after": after, "limit": limit},
        )
        return [dict(r) for r in rows.mappings()]
