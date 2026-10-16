from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.publication_service import publication_problem
from agents_factory.modules.agent_factory.publication_tests import CandidateTestResult
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.agent_factory.service import QualityGateEvidence
from agents_factory.modules.tenants.onboarding import OnboardingRepository
from typing import Literal
from .publication_preview import PreviewResult, PreviewMessage
from .workspace_publication_models import WorkspaceTestRequest


class PublicationTestRun(BaseModel):
    id: UUID
    version_id: UUID
    onboarding_revision: int | None
    source_kind: Literal["LEGACY", "AGENT_CONFIGURATION"] = "LEGACY"
    run_kind: Literal["SCENARIOS", "PREVIEW"] = "SCENARIOS"
    agent_instance_id: UUID | None = None
    draft_revision: int | None = None
    company_revision: int | None = None
    input_messages: list[PreviewMessage] | None = None
    agent_spec_digest: str
    knowledge_digest: str
    code_digest: str
    created_at: datetime
    expires_at: datetime
    result: CandidateTestResult | PreviewResult | None = None
    approved: bool | None = None
    is_current: bool = False


class PublicationEvidenceService:
    def __init__(
        self, session: AsyncSession, context: TenantContext, *, code_digest: str | None
    ) -> None:
        self.session, self.context, self.code_digest = session, context, code_digest

    async def read_run(
        self, run_id: UUID, *, check_current: bool = True
    ) -> PublicationTestRun:
        await set_tenant_context(self.session, self.context.tenant_id)
        result = await self.session.execute(
            text(
                "SELECT run.id,run.version_id,run.onboarding_revision,run.agent_spec_digest,run.knowledge_digest,"
                "run.code_digest,run.created_at,run.expires_at,result.result,review.approved, "
                "run.source_kind,run.run_kind,run.agent_instance_id,run.draft_revision,run.company_revision,run.input_messages "
                "FROM public.agent_publication_test_runs run "
                "LEFT JOIN public.agent_publication_test_results result ON result.tenant_id=run.tenant_id AND result.run_id=run.id "
                "LEFT JOIN public.agent_publication_reviews review ON review.tenant_id=run.tenant_id AND review.run_id=run.id "
                "WHERE run.tenant_id=:tenant AND run.id=:id"
            ),
            {"tenant": self.context.tenant_id, "id": run_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise publication_problem("test_run_not_found", "Test run not found", 404)
        current = False
        if (
            check_current
            and row["code_digest"] == self.code_digest
            and row["expires_at"] > datetime.now(UTC)
        ):
            if row["source_kind"] == "LEGACY":
                stored = await OnboardingRepository(self.session, self.context).read()
                current = (
                    stored is not None and stored.revision == row["onboarding_revision"]
                )
            else:
                from .publication_source import PublicationSourceResolver
                from agents_factory.common.errors import DomainError

                sources = PublicationSourceResolver(self.session, self.context)
                try:
                    source = await sources.resolve(row["version_id"])
                    await sources.require_current(source, row["draft_revision"])
                    current = True
                except DomainError:
                    current = False
        return PublicationTestRun(**dict(row), is_current=current)

    async def request_tests(self, version_id: UUID) -> PublicationTestRun:
        await set_tenant_context(self.session, self.context.tenant_id)
        await self.session.execute(
            text(
                "SELECT tenant_id FROM public.tenant_onboarding_configs WHERE tenant_id=:tenant FOR UPDATE"
            ),
            {"tenant": self.context.tenant_id},
        )
        version = await AgentSpecRepository(self.session, self.context).get_version(
            version_id
        )
        revision = await self.session.scalar(
            text(
                "SELECT onboarding_revision FROM public.panel_agent_candidates "
                "WHERE tenant_id=:tenant AND version_id=:version"
            ),
            {"tenant": self.context.tenant_id, "version": version_id},
        )
        stored = await OnboardingRepository(self.session, self.context).read()
        if version is None or revision is None:
            raise publication_problem("candidate_not_found", "Candidate not found", 404)
        if (
            version.state not in ("TEST", "QUALITY_GATE", "PRODUCTION")
            or version.compiled_spec is None
        ):
            raise publication_problem(
                "candidate_not_testable", "Prepare a test candidate first"
            )
        if (
            stored is None
            or stored.revision != revision
            or version.configuration.code_digest != self.code_digest
        ):
            raise publication_problem(
                "stale_candidate",
                "Prepare a candidate for the current revision and code",
            )
        if (
            version.compiled_spec.digest() != version.compiled_digest
            or version.configuration.approved_business_context is None
        ):
            raise publication_problem(
                "candidate_integrity_failed", "Candidate integrity failed"
            )
        pending = await self.session.scalar(
            text(
                "SELECT run.id FROM public.agent_publication_test_runs run "
                "JOIN public.outbox_jobs job ON job.tenant_id=run.tenant_id AND job.idempotency_key='agent.publication.test:'||run.id::text "
                "LEFT JOIN public.agent_publication_test_results result ON result.tenant_id=run.tenant_id AND result.run_id=run.id "
                "WHERE run.tenant_id=:tenant AND run.version_id=:version AND run.expires_at>now() AND result.run_id IS NULL "
                "AND job.status IN ('pending','dispatching','queued','processing','failed') ORDER BY run.created_at DESC LIMIT 1"
            ),
            {"tenant": self.context.tenant_id, "version": version_id},
        )
        if pending is not None:
            return await self.read_run(pending)
        run_id = uuid4()
        await self.session.execute(
            text(
                "INSERT INTO public.agent_publication_test_runs "
                "(id,tenant_id,version_id,onboarding_revision,agent_spec_digest,knowledge_digest,code_digest) "
                "VALUES(:id,:tenant,:version,:revision,:spec,:knowledge,:code)"
            ),
            {
                "id": run_id,
                "tenant": self.context.tenant_id,
                "version": version_id,
                "revision": revision,
                "spec": version.compiled_digest,
                "knowledge": version.configuration.knowledge.digest,
                "code": self.code_digest,
            },
        )
        await OutboxService(self.session).enqueue(
            context=self.context,
            idempotency_key=f"agent.publication.test:{run_id}",
            topic="agent.publication.test",
            payload={"aggregate_id": str(run_id), "test_run_id": str(run_id)},
        )
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.publication_tests_requested",
            entity_type="agent_spec",
            entity_id=version_id,
            payload={"run_id": str(run_id)},
        )
        return await self.read_run(run_id)

    async def save_result(
        self, run_id: UUID, result: CandidateTestResult | PreviewResult
    ) -> None:
        run = await self.read_run(run_id, check_current=False)
        if (run.run_kind == "PREVIEW") != isinstance(result, PreviewResult):
            raise publication_problem(
                "test_result_kind_mismatch",
                "El resultado no corresponde al tipo de prueba.",
            )
        await self.session.execute(
            text(
                "INSERT INTO public.agent_publication_test_results(run_id,tenant_id,result) "
                "VALUES(:id,:tenant,:result) ON CONFLICT(run_id) DO NOTHING"
            ).bindparams(bindparam("result", type_=JSONB)),
            {
                "id": run_id,
                "tenant": self.context.tenant_id,
                "result": result.model_dump(mode="json"),
            },
        )

    async def review(
        self, run_id: UUID, *, approved: bool, expected_revision: int
    ) -> PublicationTestRun:
        run = await self.read_run(run_id)
        if run.source_kind != "LEGACY" or run.run_kind != "SCENARIOS":
            raise publication_problem("test_run_not_found", "Test run not found", 404)
        await self.session.execute(
            text(
                "SELECT tenant_id FROM public.tenant_onboarding_configs "
                "WHERE tenant_id=:tenant FOR UPDATE"
            ),
            {"tenant": self.context.tenant_id},
        )
        stored = await OnboardingRepository(self.session, self.context).read()
        if self.context.actor_id is None or run.approved is not None:
            raise publication_problem(
                "review_unavailable",
                "A reviewed run is immutable; request a new test run",
            )
        if (
            stored is None
            or stored.revision != expected_revision
            or run.onboarding_revision != expected_revision
            or run.code_digest != self.code_digest
            or run.expires_at <= datetime.now(UTC)
        ):
            raise publication_problem("stale_test_run", "Test run is not current")
        if not isinstance(run.result, CandidateTestResult) or (
            approved and not run.result.checks_passed
        ):
            raise publication_problem(
                "test_run_not_passed", "Only complete passing checks can be approved"
            )
        await self.session.execute(
            text(
                "INSERT INTO public.agent_publication_reviews(id,run_id,tenant_id,reviewer_id,approved) "
                "VALUES(:id,:run,:tenant,:reviewer,:approved)"
            ),
            {
                "id": uuid4(),
                "run": run_id,
                "tenant": self.context.tenant_id,
                "reviewer": self.context.actor_id,
                "approved": approved,
            },
        )
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.publication_tests_reviewed",
            entity_type="agent_spec",
            entity_id=run.version_id,
            payload={"run_id": str(run_id), "approved": approved},
        )
        return await self.read_run(run_id)


class PersistedPanelQualityGate:
    def __init__(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        run_id: UUID | None = None,
    ) -> None:
        self.session, self.context, self.run_id = session, context, run_id

    async def evaluate(
        self, *, agent_spec_digest: str, knowledge_digest: str, code_digest: str
    ) -> QualityGateEvidence | None:
        await set_tenant_context(self.session, self.context.tenant_id)
        result = await self.session.execute(
            text(
                "SELECT review.id,result.result FROM public.agent_publication_test_runs run "
                "JOIN public.agent_publication_test_results result ON result.tenant_id=run.tenant_id AND result.run_id=run.id "
                "JOIN public.agent_publication_reviews review ON review.tenant_id=run.tenant_id AND review.run_id=run.id "
                "JOIN public.tenant_onboarding_configs config ON config.tenant_id=run.tenant_id "
                "WHERE run.tenant_id=:tenant AND run.source_kind='LEGACY' AND run.run_kind='SCENARIOS' AND run.agent_spec_digest=:spec AND run.knowledge_digest=:knowledge "
                "AND run.code_digest=:code AND run.expires_at>now() AND config.revision=run.onboarding_revision "
                "AND review.approved AND (CAST(:run_id AS uuid) IS NULL OR run.id=CAST(:run_id AS uuid)) ORDER BY review.created_at DESC LIMIT 1"
            ),
            {
                "tenant": self.context.tenant_id,
                "spec": agent_spec_digest,
                "knowledge": knowledge_digest,
                "code": code_digest,
                "run_id": self.run_id,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        checks = CandidateTestResult.model_validate(row["result"])
        if not checks.checks_passed:
            return None
        return QualityGateEvidence(
            decision_id=row["id"],
            passed=True,
            agent_spec_digest=agent_spec_digest,
            knowledge_digest=knowledge_digest,
            code_digest=code_digest,
        )


class WorkspacePublicationEvidenceService:
    """Administrative evidence commands scoped to one instance and source revision."""

    def __init__(
        self, session: AsyncSession, context: TenantContext, *, code_digest: str | None
    ):
        from .workspace_publication_repository import WorkspacePublicationRepository
        from .publication_source import PublicationSourceResolver

        self.session, self.context, self.code_digest = session, context, code_digest
        self.repository = WorkspacePublicationRepository(session, context)
        self.sources = PublicationSourceResolver(session, context)
        self.evidence = PublicationEvidenceService(
            session, context, code_digest=code_digest
        )

    async def read(self, agent_id: UUID, run_id: UUID) -> PublicationTestRun:
        run = await self.evidence.read_run(run_id)
        if (
            run.source_kind != "AGENT_CONFIGURATION"
            or run.agent_instance_id != agent_id
        ):
            raise publication_problem(
                "test_run_not_found", "Prueba no encontrada.", 404
            )
        return run

    async def request(
        self, agent_id: UUID, version_id: UUID, request: "WorkspaceTestRequest"
    ) -> PublicationTestRun:
        import json

        await self.sources.editable(agent_id, request.expected_revision)
        source = await self.sources.resolve(version_id)
        if (
            source.source_kind != "AGENT_CONFIGURATION"
            or source.agent_instance_id != agent_id
        ):
            raise publication_problem(
                "candidate_not_found", "Candidato no encontrado.", 404
            )
        await self.sources.require_current(source, request.expected_revision)
        if source.code_digest != self.code_digest or self.context.actor_id is None:
            raise publication_problem(
                "stale_candidate", "Prepara una versión para el código actual."
            )
        inputs = (
            None
            if request.messages is None
            else [m.model_dump() for m in request.messages]
        )
        same = await self.repository.request_by_key(
            self.context.actor_id, request.request_key
        )
        if same is not None:
            if (
                same["version_id"] != version_id
                or same["run_kind"] != request.run_kind
                or same["input_messages"] != inputs
                or same["draft_revision"] != request.expected_revision
            ):
                raise publication_problem(
                    "test_request_key_conflict",
                    "La solicitud ya existe con otro contenido.",
                )
            return await self.read(agent_id, same["id"])
        pending = await self.repository.pending_run(
            agent_id, version_id, request.run_kind
        )
        if pending is not None:
            raise publication_problem(
                "test_run_pending",
                "Ya hay una prueba pendiente; consulta su estado antes de iniciar otra.",
            )
        maximum = 30 if request.run_kind == "PREVIEW" else 6
        if await self.repository.recent_count(agent_id, request.run_kind) >= maximum:
            raise publication_problem(
                "test_rate_limit",
                "Se alcanzó el límite por hora; espera antes de volver a probar.",
                429,
            )
        version = await AgentSpecRepository(self.session, self.context).get_version(
            version_id
        )
        if (
            version is None
            or version.state not in ("TEST", "QUALITY_GATE", "PRODUCTION")
            or version.compiled_spec is None
            or version.compiled_spec.digest() != version.compiled_digest
        ):
            raise publication_problem(
                "candidate_integrity_failed",
                "El candidato no supera la verificación de integridad.",
            )
        run_id = uuid4()
        await self.repository.insert_run(
            id=run_id,
            version=version_id,
            kind=request.run_kind,
            agent=agent_id,
            revision=source.revision,
            company_revision=source.company_revision,
            messages=None if inputs is None else json.dumps(inputs),
            actor=self.context.actor_id,
            key=request.request_key,
            spec=version.compiled_digest,
            knowledge=version.configuration.knowledge.digest,
            code=self.code_digest,
        )
        await OutboxService(self.session).enqueue(
            context=self.context,
            idempotency_key=f"agent.publication.test:{run_id}",
            topic="agent.publication.test",
            payload={"aggregate_id": str(run_id), "test_run_id": str(run_id)},
        )
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.workspace_tests_requested",
            entity_type="agent_spec",
            entity_id=version_id,
            payload={"run_id": str(run_id), "kind": request.run_kind},
        )
        return await self.read(agent_id, run_id)

    async def review(
        self,
        agent_id: UUID,
        run_id: UUID,
        *,
        expected_revision: int,
        approved: bool,
        confirm_review: bool,
    ) -> PublicationTestRun:
        await self.sources.editable(agent_id, expected_revision)
        await self.repository.lock_review(run_id)
        run = await self.read(agent_id, run_id)
        if run.run_kind != "SCENARIOS":
            raise publication_problem(
                "preview_not_reviewable",
                "La conversación de prueba no sustituye los escenarios requeridos.",
            )
        if not run.is_current or run.draft_revision != expected_revision:
            raise publication_problem(
                "stale_test_run", "Prepara pruebas para el borrador actual."
            )
        if run.approved is not None or self.context.actor_id is None:
            raise publication_problem(
                "review_unavailable",
                "La decisión es inmutable; solicita nuevas pruebas.",
            )
        if not isinstance(run.result, CandidateTestResult) or (
            approved and not run.result.checks_passed
        ):
            raise publication_problem(
                "test_run_not_passed",
                "Solo se aprueban escenarios completos y satisfactorios.",
            )
        if approved and not confirm_review:
            raise publication_problem(
                "review_confirmation_required",
                "Confirma que revisaste las respuestas exactas.",
                422,
            )
        await self.repository.insert_review(
            run_id, self.context.actor_id, approved, uuid4()
        )
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.workspace_tests_reviewed",
            entity_type="agent_spec",
            entity_id=run.version_id,
            payload={"run_id": str(run_id), "approved": approved},
        )
        return await self.read(agent_id, run_id)
