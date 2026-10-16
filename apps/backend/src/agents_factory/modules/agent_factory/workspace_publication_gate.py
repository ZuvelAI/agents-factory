"""Exact-source quality gate; preview results never authorize publication."""

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.common.context import TenantContext
from .publication_evidence import WorkspacePublicationEvidenceService
from .publication_source import PublicationSourceResolver
from .publication_tests import CandidateTestResult
from .service import QualityGateEvidence
from .workspace_publication_repository import WorkspacePublicationRepository


class WorkspaceQualityGate:
    def __init__(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        agent_id: UUID,
        run_id: UUID,
        expected_revision: int,
        code_digest: str,
    ):
        self.session, self.context = session, context
        self.agent_id, self.run_id, self.expected_revision, self.code_digest = (
            agent_id,
            run_id,
            expected_revision,
            code_digest,
        )

    async def evaluate(
        self, *, agent_spec_digest: str, knowledge_digest: str, code_digest: str
    ) -> QualityGateEvidence | None:
        run = await WorkspacePublicationEvidenceService(
            self.session, self.context, code_digest=self.code_digest
        ).read(self.agent_id, self.run_id)
        if (
            run.run_kind != "SCENARIOS"
            or not run.is_current
            or run.approved is not True
            or run.draft_revision != self.expected_revision
            or not isinstance(run.result, CandidateTestResult)
            or not run.result.checks_passed
            or (run.agent_spec_digest, run.knowledge_digest, run.code_digest)
            != (agent_spec_digest, knowledge_digest, code_digest)
        ):
            return None
        source = await PublicationSourceResolver(self.session, self.context).resolve(
            run.version_id
        )
        await PublicationSourceResolver(self.session, self.context).require_current(
            source, self.expected_revision
        )
        decision = await WorkspacePublicationRepository(
            self.session, self.context
        ).decision(run.id)
        return (
            None
            if decision is None
            else QualityGateEvidence(
                decision, True, agent_spec_digest, knowledge_digest, code_digest
            )
        )
