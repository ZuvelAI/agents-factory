from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text, bindparam
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.account_lifecycle import lock_account_lifecycle
from agents_factory.common.errors import DomainError
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.approved_knowledge import (
    ApprovedKnowledgeRepository,
)
from agents_factory.modules.agent_factory.models import AgentSpecVersion
from agents_factory.modules.agent_factory.channel_binding import (
    AccountAgentBinding,
    AccountAgentBindingRepository,
)
from agents_factory.modules.agent_factory.onboarding_projection import (
    project_onboarding,
    projection_blockers,
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


class TestRunReference(BaseModel):
    id: UUID
    version_id: UUID
    onboarding_revision: int
    created_at: datetime
    approved: bool | None
    completed: bool


class RollbackTarget(BaseModel):
    whatsapp_account_id: UUID
    id: UUID
    version_number: int


class PublicationState(BaseModel):
    saved_revision: int
    candidates: list[AgentSpecVersion]
    accounts: list[PublicationAccount]
    blockers: list[str]
    bindings: list[AccountAgentBinding] = []
    test_runs: list[TestRunReference] = []
    rollback_targets: list[RollbackTarget] = []


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
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        code_digest: str | None,
        compatible_versions: dict[UUID, str] | None = None,
    ) -> None:
        self.session, self.context, self.code_digest = session, context, code_digest
        self.compatible_versions = dict(compatible_versions or {})
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
            blockers.extend(projection_blockers(stored.configuration))
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
            test_runs=[
                TestRunReference(**row)
                for row in (
                    await self.session.execute(
                        text(
                            "SELECT run.id,run.version_id,run.onboarding_revision,run.created_at,review.approved,"
                            "(result.run_id IS NOT NULL) AS completed FROM public.agent_publication_test_runs run "
                            "LEFT JOIN public.agent_publication_reviews review ON review.tenant_id=run.tenant_id AND review.run_id=run.id "
                            "LEFT JOIN public.agent_publication_test_results result ON result.tenant_id=run.tenant_id AND result.run_id=run.id "
                            "WHERE run.tenant_id=:tenant AND run.source_kind='LEGACY' ORDER BY run.created_at DESC,run.id DESC LIMIT 100"
                        ),
                        {"tenant": self.context.tenant_id},
                    )
                ).mappings()
            ],
            rollback_targets=[
                RollbackTarget(**row)
                for row in (
                    await self.session.execute(
                        text(
                            "SELECT binding.whatsapp_account_id,version.id,version.version_number "
                            "FROM public.account_agent_bindings binding "
                            "JOIN public.agent_spec_versions version ON version.tenant_id=binding.tenant_id AND version.agent_instance_id=binding.agent_instance_id "
                            "WHERE binding.tenant_id=:tenant AND version.state='PRODUCTION' AND version.id<>binding.version_id "
                            "AND CAST(:code AS text) IS NOT NULL AND (version.configuration->>'code_digest'=:code "
                            "OR version.configuration->>'code_digest'=(CAST(:compatible AS jsonb)->>CAST(version.id AS text))) "
                            "AND EXISTS(SELECT 1 FROM public.agent_spec_deployments deployment WHERE deployment.tenant_id=version.tenant_id AND deployment.version_id=version.id AND deployment.action='PUBLISH') "
                            "ORDER BY binding.whatsapp_account_id,version.version_number DESC"
                        ).bindparams(bindparam("compatible", type_=JSONB)),
                        {
                            "tenant": self.context.tenant_id,
                            "code": self.code_digest,
                            "compatible": {
                                str(key): value
                                for key, value in self.compatible_versions.items()
                            },
                        },
                    )
                ).mappings()
            ],
            bindings=[
                AccountAgentBinding(**row)
                for row in (
                    await self.session.execute(
                        text(
                            "SELECT * FROM public.account_agent_bindings WHERE tenant_id=:tenant ORDER BY whatsapp_account_id"
                        ),
                        {"tenant": self.context.tenant_id},
                    )
                ).mappings()
            ],
        )

    async def _lock_publication_account(
        self, account_id: UUID
    ) -> AccountAgentBindingRepository:
        await self._existing_tenant()
        await lock_account_lifecycle(self.session, self.context.tenant_id, account_id)
        await self.session.execute(
            text(
                "SELECT tenant_id FROM public.tenant_onboarding_configs WHERE tenant_id=:tenant FOR UPDATE"
            ),
            {"tenant": self.context.tenant_id},
        )
        account = await self.session.execute(
            text(
                "SELECT status,health_status FROM public.whatsapp_accounts "
                "WHERE tenant_id=:tenant AND id=:account FOR UPDATE"
            ),
            {"tenant": self.context.tenant_id, "account": account_id},
        )
        row = account.mappings().one_or_none()
        if row is None:
            raise publication_problem(
                "whatsapp_account_not_found", "Account not found", 404
            )
        if row["status"] != "active" or row["health_status"] != "HEALTHY":
            raise publication_problem(
                "whatsapp_account_unhealthy", "A healthy active account is required"
            )
        return AccountAgentBindingRepository(self.session, self.context)

    async def publish(
        self,
        *,
        version_id: UUID,
        whatsapp_account_id: UUID,
        expected_revision: int,
        test_run_id: UUID,
        expected_binding_revision: int,
    ) -> AccountAgentBinding:
        from agents_factory.modules.agent_factory.publication_evidence import (
            PublicationEvidenceService,
            PersistedPanelQualityGate,
        )

        bindings = await self._lock_publication_account(whatsapp_account_id)
        stored = await self.onboarding.read()
        version = await self.specs.get_version(version_id)
        run = await PublicationEvidenceService(
            self.session, self.context, code_digest=self.code_digest
        ).read_run(test_run_id)
        if run.source_kind != "LEGACY" or run.run_kind != "SCENARIOS":
            raise publication_problem("test_run_not_found", "Test run not found", 404)
        if (
            stored is None
            or stored.revision != expected_revision
            or run.onboarding_revision != expected_revision
        ):
            raise publication_problem(
                "stale_onboarding_revision", "Reload configuration before publishing"
            )
        if (
            version is None
            or run.version_id != version_id
            or version.configuration.code_digest != self.code_digest
        ):
            raise publication_problem(
                "stale_candidate", "Candidate does not match current code and test run"
            )
        if (
            version.compiled_spec is None
            or version.compiled_spec.digest() != version.compiled_digest
        ):
            raise publication_problem(
                "candidate_integrity_failed", "Candidate digest mismatch"
            )
        gate = PersistedPanelQualityGate(self.session, self.context, run_id=test_run_id)
        proof = await gate.evaluate(
            agent_spec_digest=version.compiled_digest,
            knowledge_digest=version.configuration.knowledge.digest,
            code_digest=self.code_digest,
        )
        if proof is None:
            raise publication_problem(
                "production_quality_gate_required",
                "Current passing reviewed evidence is required",
            )
        current = await bindings.get_for_account(whatsapp_account_id)
        if current is not None and current.version_id == version_id:
            return current
        if (0 if current is None else current.revision) != expected_binding_revision:
            raise publication_problem(
                "stale_account_binding", "Reload the current account binding"
            )
        lifecycle = AgentSpecLifecycleService(repository=self.specs, quality_gate=gate)
        if version.state == "TEST":
            version = await lifecycle.enter_quality_gate(version.id)
        if version.state != "PRODUCTION":
            version = await lifecycle.publish_production(version.id)
        binding = await bindings.bind(
            whatsapp_account_id,
            version,
            expected_revision=expected_binding_revision,
            action="PUBLISH",
        )
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.account_published",
            entity_type="whatsapp_account",
            entity_id=whatsapp_account_id,
            payload={
                "version_id": str(version.id),
                "binding_revision": binding.revision,
            },
        )
        return binding

    async def rollback(
        self,
        *,
        whatsapp_account_id: UUID,
        target_version_id: UUID,
        expected_binding_revision: int,
    ) -> AccountAgentBinding:
        bindings = await self._lock_publication_account(whatsapp_account_id)
        current = await bindings.get_for_account(whatsapp_account_id)
        target = await self.specs.get_version(target_version_id)
        if current is None or current.revision != expected_binding_revision:
            raise publication_problem(
                "stale_account_binding", "Reload the current account binding"
            )
        if target is None or target.agent_instance_id != current.agent_instance_id:
            raise publication_problem(
                "incompatible_agent_spec_rollback",
                "Target must belong to the current agent",
            )
        version = await AgentSpecLifecycleService(repository=self.specs).rollback_to(
            agent_instance_id=current.agent_instance_id,
            target_version_id=target_version_id,
            current_code_digest=self.code_digest or "",
            compatible_versions=self.compatible_versions,
        )
        binding = await bindings.bind(
            whatsapp_account_id,
            version,
            expected_revision=expected_binding_revision,
            action="ROLLBACK",
        )
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.account_rolled_back",
            entity_type="whatsapp_account",
            entity_id=whatsapp_account_id,
            payload={
                "version_id": str(version.id),
                "binding_revision": binding.revision,
            },
        )
        return binding

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
            if self.code_digest is None:
                raise ValueError("deployed code digest is required")
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
