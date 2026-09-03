from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.service import QualityGateEvidence
from agents_factory.modules.evals.models import QualityGateDecision, QualityGateOverview


class PersistedProductionQualityGate:
    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def evaluate(
        self,
        *,
        agent_spec_digest: str,
        knowledge_digest: str,
        code_digest: str,
    ) -> QualityGateEvidence | None:
        await set_tenant_context(self._session, self._tenant_id)
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT id,passed,agent_spec_digest,knowledge_digest,code_digest "
                        "FROM public.quality_gate_decisions WHERE tenant_id=:tenant AND "
                        "agent_spec_digest=:agent AND knowledge_digest=:knowledge AND "
                        "code_digest=:code ORDER BY decided_at DESC,id DESC LIMIT 1"
                    ),
                    {
                        "tenant": self._tenant_id,
                        "agent": agent_spec_digest,
                        "knowledge": knowledge_digest,
                        "code": code_digest,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return QualityGateEvidence(
            decision_id=row["id"],
            passed=row["passed"],
            agent_spec_digest=row["agent_spec_digest"],
            knowledge_digest=row["knowledge_digest"],
            code_digest=row["code_digest"],
        )


class PersistedKnowledgeQualityGate:
    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def evaluate(self, *, knowledge_digest: str) -> bool:
        await set_tenant_context(self._session, self._tenant_id)
        return bool(
            await self._session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM public.quality_gate_decisions AS "
                    "decision JOIN public.agent_spec_versions AS agent ON "
                    "agent.tenant_id=decision.tenant_id AND "
                    "agent.compiled_digest=decision.agent_spec_digest AND "
                    "agent.configuration #>> '{knowledge,digest}'="
                    "decision.knowledge_digest AND agent.configuration ->> "
                    "'code_digest'=decision.code_digest WHERE decision.tenant_id=:tenant "
                    "AND decision.knowledge_digest=:digest AND decision.passed AND "
                    "agent.state IN ('QUALITY_GATE','PRODUCTION'))"
                ),
                {"tenant": self._tenant_id, "digest": knowledge_digest},
            )
        )


async def quality_gate_overview(
    session: AsyncSession, *, tenant_id: UUID
) -> QualityGateOverview:
    await set_tenant_context(session, tenant_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT decision.id,decision.eval_run_id,decision.passed,"
                    "decision.agent_spec_digest,decision.knowledge_digest,"
                    "decision.code_digest,decision.hard_blockers,run.passed_cases,"
                    "run.failed_cases,run.runner_version,decision.decided_at FROM "
                    "public.quality_gate_decisions AS decision JOIN public.eval_runs AS run "
                    "ON run.tenant_id=decision.tenant_id AND run.id=decision.eval_run_id "
                    "WHERE decision.tenant_id=:tenant ORDER BY decision.decided_at DESC,"
                    "decision.id DESC LIMIT 1"
                ),
                {"tenant": tenant_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return QualityGateOverview(
        latest=None if row is None else QualityGateDecision.model_validate(dict(row))
    )
