from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.approved_knowledge import (
    ApprovedKnowledgeRepository,
)
from agents_factory.modules.agent_factory.models import AgentSpecVersion
from agents_factory.modules.agent_factory.onboarding_projection import (
    project_onboarding,
)
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.agent_factory.service import AgentSpecLifecycleService
from agents_factory.modules.tenants.onboarding import (
    OnboardingRepository,
    OnboardingService,
)
from agents_factory.modules.tenants.repository import TenantRepository


class PublicationAccount(BaseModel):
    id: UUID
    display_phone_number: str | None
    status: str
    health_status: str


class PublicationState(BaseModel):
    saved_revision: int
    candidates: list[AgentSpecVersion]
    accounts: list[PublicationAccount]
    blockers: list[str]


def publication_problem(code: str, detail: str, status: int = 409) -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/" + code,
        title="Agent publication",
        status=status,
        detail=detail,
        code=code,
    )


class PanelPublicationService:
    def __init__(
        self, session: AsyncSession, context: TenantContext, *, code_digest: str | None
    ) -> None:
        self.session, self.context, self.code_digest = session, context, code_digest
        self.onboarding = OnboardingRepository(session, context)
        self.specs = AgentSpecRepository(session, context)

    async def _existing_tenant(self) -> None:
        if await TenantRepository(self.session).get(self.context.tenant_id) is None:
            raise publication_problem("tenant_not_found", "Tenant not found", 404)
        await set_tenant_context(self.session, self.context.tenant_id)

    async def read_state(self) -> PublicationState:
        await self._existing_tenant()
        stored = await self.onboarding.read()
        blockers = []
        if not self.code_digest or not re.fullmatch(r"[0-9a-f]{64}", self.code_digest):
            blockers.append("Falta la huella verificable del código desplegado.")
        response = await OnboardingService(self.session, self.context).read()
        for step in response.steps[:8]:
            if step.key != "knowledge":
                blockers.extend(
                    b for b in step.blockers if not b.startswith("Completa primero:")
                )
        if stored is None:
            blockers.append("Guarda la configuración antes de preparar el agente.")
        else:
            knowledge = stored.configuration.knowledge
            if (
                not knowledge.review_confirmed
                or knowledge.critical_conflicts
                or any(
                    not value.strip()
                    for value in (
                        knowledge.source_name,
                        knowledge.source_reference,
                        knowledge.approved_summary,
                    )
                )
            ):
                blockers.append(
                    "Knowledge requiere contenido aprobado, revisión confirmada y cero conflictos críticos."
                )
        rows = await self.session.execute(
            text(
                "SELECT version_id FROM public.panel_agent_candidates WHERE tenant_id=:tenant "
                "ORDER BY created_at DESC,version_id DESC LIMIT 20"
            ),
            {"tenant": self.context.tenant_id},
        )
        candidates = []
        for version_id in rows.scalars():
            version = await self.specs.get_version(version_id)
            if version is not None:
                candidates.append(version)
        accounts = await self.session.execute(
            text(
                "SELECT id,display_phone_digits AS display_phone_number,status,health_status FROM public.whatsapp_accounts "
                "WHERE tenant_id=:tenant ORDER BY created_at,id LIMIT 100"
            ),
            {"tenant": self.context.tenant_id},
        )
        return PublicationState(
            saved_revision=0 if stored is None else stored.revision,
            candidates=candidates,
            accounts=[PublicationAccount(**row) for row in accounts.mappings()],
            blockers=list(dict.fromkeys(blockers)),
        )

    async def prepare_candidate(self, *, expected_revision: int) -> AgentSpecVersion:
        await self._existing_tenant()
        # Serialize preparation with wizard saves and concurrent candidate creation.
        await self.session.execute(
            text(
                "SELECT tenant_id FROM public.tenant_onboarding_configs "
                "WHERE tenant_id=:tenant FOR UPDATE"
            ),
            {"tenant": self.context.tenant_id},
        )
        stored = await self.onboarding.read()
        if stored is None or stored.revision != expected_revision:
            raise publication_problem(
                "stale_onboarding_revision", "Reload the saved configuration"
            )
        state = await self.read_state()
        if state.blockers:
            raise publication_problem(
                "publication_configuration_incomplete", "; ".join(state.blockers)
            )
        existing = await self.session.scalar(
            text(
                "SELECT version_id FROM public.panel_agent_candidates "
                "WHERE tenant_id=:tenant AND onboarding_revision=:revision AND code_digest=:code"
            ),
            {
                "tenant": self.context.tenant_id,
                "revision": expected_revision,
                "code": self.code_digest,
            },
        )
        if existing:
            version = await self.specs.get_version(existing)
            if version is None:
                raise publication_problem(
                    "candidate_missing", "Candidate integrity check failed"
                )
            return version
        try:
            knowledge = await ApprovedKnowledgeRepository(
                self.session, self.context
            ).freeze(stored.configuration.knowledge)
            config = project_onboarding(
                stored.configuration, knowledge, self.code_digest
            )
        except ValueError as error:
            raise publication_problem(
                "publication_configuration_incomplete", str(error)
            ) from None
        lifecycle = AgentSpecLifecycleService(repository=self.specs)
        if state.candidates:
            base = state.candidates[0]
            draft = await lifecycle.create_draft(
                agent_instance_id=base.agent_instance_id,
                based_on_version_id=base.id,
                configuration=config,
            )
        else:
            _, draft = await lifecycle.create_instance(configuration=config)
        version = await lifecycle.promote_to_test(draft.id)
        await self.session.execute(
            text(
                "INSERT INTO public.panel_agent_candidates "
                "(tenant_id,onboarding_revision,code_digest,version_id) VALUES(:tenant,:revision,:code,:version)"
            ),
            {
                "tenant": self.context.tenant_id,
                "revision": expected_revision,
                "code": self.code_digest,
                "version": version.id,
            },
        )
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.panel_candidate_prepared",
            entity_type="agent_spec",
            entity_id=version.id,
            payload={"revision": expected_revision, "digest": version.compiled_digest},
        )
        return version
