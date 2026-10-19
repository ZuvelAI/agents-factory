"""Publication provenance SQL. Caller owns the transaction and tenant context."""

from typing import Any
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.common.context import TenantContext
from agents_factory.common.account_lifecycle import lock_account_lifecycle
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

    async def request_by_key(self, actor: UUID, key: UUID) -> dict[str, Any] | None:
        return await self.one(
            "SELECT * FROM public.agent_publication_test_runs WHERE tenant_id=:tenant AND requested_by=:actor AND request_key=:key",
            actor=actor,
            key=key,
        )

    async def pending_run(
        self, agent: UUID, version: UUID, kind: str
    ) -> dict[str, Any] | None:
        return await self.one(
            "SELECT run.id FROM public.agent_publication_test_runs run LEFT JOIN public.agent_publication_test_results result ON result.tenant_id=run.tenant_id AND result.run_id=run.id WHERE run.tenant_id=:tenant AND run.agent_instance_id=:agent AND run.version_id=:version AND run.run_kind=:kind AND run.expires_at>now() AND result.run_id IS NULL ORDER BY run.created_at DESC LIMIT 1",
            agent=agent,
            version=version,
            kind=kind,
        )

    async def recent_count(self, agent: UUID, kind: str) -> int:
        row = await self.one(
            "SELECT count(*) AS count FROM public.agent_publication_test_runs WHERE tenant_id=:tenant AND agent_instance_id=:agent AND run_kind=:kind AND created_at>now()-interval '1 hour'",
            agent=agent,
            kind=kind,
        )
        assert row is not None
        return int(row["count"])

    async def insert_run(self, **params: Any) -> None:
        await self.one(
            "INSERT INTO public.agent_publication_test_runs (id,tenant_id,version_id,onboarding_revision,source_kind,run_kind,agent_instance_id,draft_revision,company_revision,input_messages,requested_by,request_key,agent_spec_digest,knowledge_digest,code_digest) VALUES (:id,:tenant,:version,NULL,'AGENT_CONFIGURATION',:kind,:agent,:revision,:company_revision,CAST(:messages AS jsonb),:actor,:key,:spec,:knowledge,:code) RETURNING id",
            **params,
        )

    async def lock_review(self, run_id: UUID) -> None:
        await self.one(
            "SELECT pg_advisory_xact_lock(hashtextextended(:key,0))",
            key=f"publication-review:{self.context.tenant_id}:{run_id}",
        )

    async def insert_review(
        self, run_id: UUID, actor_id: UUID, approved: bool, decision_id: UUID
    ) -> None:
        await self.one(
            "INSERT INTO public.agent_publication_reviews (id,tenant_id,run_id,reviewer_id,approved) VALUES(:id,:tenant,:run,:actor,:approved) RETURNING id",
            id=decision_id,
            run=run_id,
            actor=actor_id,
            approved=approved,
        )

    async def decision(self, run_id: UUID) -> UUID | None:
        row = await self.one(
            "SELECT id FROM public.agent_publication_reviews WHERE tenant_id=:tenant AND run_id=:run AND approved",
            run=run_id,
        )
        return row["id"] if row else None

    async def lock_account(self, account_id: UUID) -> dict[str, Any] | None:
        await lock_account_lifecycle(self.session, self.context.tenant_id, account_id)
        return await self.one(
            "SELECT * FROM public.whatsapp_accounts WHERE tenant_id=:tenant AND id=:account FOR UPDATE",
            account=account_id,
        )

    async def page(
        self, kind: str, agent_id: UUID, at: Any, after_id: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        # Only internally selected, fixed SQL fragments; no user-provided identifiers.
        relations = {
            "candidates": (
                "workspace_agent_candidates",
                "version_id",
                "agent_instance_id=:agent",
            ),
            "runs": (
                "agent_publication_test_runs",
                "id",
                "agent_instance_id=:agent AND source_kind='AGENT_CONFIGURATION'",
            ),
            "accounts": ("whatsapp_accounts", "id", "true"),
            "versions": (
                "agent_spec_versions",
                "id",
                "agent_instance_id=:agent AND state='PRODUCTION'",
            ),
        }
        table, key, where = relations[kind]
        await set_tenant_context(self.session, self.context.tenant_id)
        result = await self.session.execute(
            text(
                f"SELECT * FROM public.{table} WHERE tenant_id=:tenant AND {where} AND (CAST(:at AS timestamptz) IS NULL OR (created_at,{key})<(CAST(:at AS timestamptz),CAST(:after AS uuid))) ORDER BY created_at DESC,{key} DESC LIMIT :limit"
            ),
            {
                "tenant": self.context.tenant_id,
                "agent": agent_id,
                "at": at,
                "after": after_id,
                "limit": limit,
            },
        )
        return [dict(row) for row in result.mappings()]

    async def bindings_for_agent(self, agent_id: UUID) -> list[dict[str, Any]]:
        await set_tenant_context(self.session, self.context.tenant_id)
        result = await self.session.execute(
            text(
                "SELECT * FROM public.account_agent_bindings WHERE tenant_id=:tenant AND agent_instance_id=:agent ORDER BY whatsapp_account_id LIMIT 101"
            ),
            {"tenant": self.context.tenant_id, "agent": agent_id},
        )
        return [dict(row) for row in result.mappings()]

    async def binding_for_account(self, account_id: UUID) -> dict[str, Any] | None:
        return await self.one(
            "SELECT * FROM public.account_agent_bindings WHERE tenant_id=:tenant AND whatsapp_account_id=:account",
            account=account_id,
        )
