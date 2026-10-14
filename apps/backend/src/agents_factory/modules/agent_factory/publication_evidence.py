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


class PublicationTestRun(BaseModel):
    id: UUID
    version_id: UUID
    onboarding_revision: int
    agent_spec_digest: str
    knowledge_digest: str
    code_digest: str
    created_at: datetime
    expires_at: datetime
    result: CandidateTestResult | None = None
    approved: bool | None = None
    is_current: bool = False


class PublicationEvidenceService:
    def __init__(
        self, session: AsyncSession, context: TenantContext, *, code_digest: str | None
    ) -> None:
        self.session, self.context, self.code_digest = session, context, code_digest

    async def read_run(self, run_id: UUID) -> PublicationTestRun:
        await set_tenant_context(self.session, self.context.tenant_id)
        result = await self.session.execute(
            text(
                "SELECT run.id,run.version_id,run.onboarding_revision,run.agent_spec_digest,run.knowledge_digest,"
                "run.code_digest,run.created_at,run.expires_at,result.result,review.approved "
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
        stored = await OnboardingRepository(self.session, self.context).read()
        current = (
            stored is not None
            and stored.revision == row["onboarding_revision"]
            and row["code_digest"] == self.code_digest
            and row["expires_at"] > datetime.now(UTC)
        )
        return PublicationTestRun(**dict(row), is_current=current)

    async def request_tests(self, version_id: UUID) -> PublicationTestRun:
        await set_tenant_context(self.session, self.context.tenant_id)
        await self.session.execute(text("SELECT tenant_id FROM public.tenant_onboarding_configs WHERE tenant_id=:tenant FOR UPDATE"),
                                   {"tenant":self.context.tenant_id})
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
        pending=await self.session.scalar(text(
            "SELECT run.id FROM public.agent_publication_test_runs run "
            "JOIN public.outbox_jobs job ON job.tenant_id=run.tenant_id AND job.idempotency_key='agent.publication.test:'||run.id::text "
            "LEFT JOIN public.agent_publication_test_results result ON result.tenant_id=run.tenant_id AND result.run_id=run.id "
            "WHERE run.tenant_id=:tenant AND run.version_id=:version AND run.expires_at>now() AND result.run_id IS NULL "
            "AND job.status IN ('pending','dispatching','queued','processing','failed') ORDER BY run.created_at DESC LIMIT 1"),
            {"tenant":self.context.tenant_id,"version":version_id})
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

    async def save_result(self, run_id: UUID, result: CandidateTestResult) -> None:
        await self.read_run(run_id)
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
        if run.result is None or (approved and not run.result.checks_passed):
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
                "WHERE run.tenant_id=:tenant AND run.agent_spec_digest=:spec AND run.knowledge_digest=:knowledge "
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
