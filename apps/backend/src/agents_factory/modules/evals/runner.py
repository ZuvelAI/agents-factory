from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import cast

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.evals.models import (
    HardBlocker,
    QualityGateDecision,
    QualityGateRunRequest,
)
from evals.graders import redact_artifact
from evals.run_local import RUNNER_VERSION, load_cases, run_cases


REQUIRED_PRODUCTION_SUITES = frozenset(
    {
        "global",
        "security",
        "tenant_isolation",
        "human_control",
        "failure_handling",
        "appointments",
        "orders",
        "returns_claims",
        "runtime_smoke",
        "release_acceptance",
    }
)


class ProductionEvalRunner:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def run(self, request: QualityGateRunRequest) -> QualityGateDecision:
        await set_tenant_context(self._session, self._context.tenant_id)
        await self._require_exact_candidate(request)
        suite_paths = tuple(_case_path(name) for name in request.suites)
        suite_bytes = b"".join(path.read_bytes() for path in suite_paths)
        suite_digest = hashlib.sha256(suite_bytes).hexdigest()
        cases = tuple(case for path in suite_paths for case in load_cases(path))
        run_id = new_uuid7()
        await self._session.execute(
            text(
                "INSERT INTO public.eval_runs (id,tenant_id,suite_digest,runner_version,"
                "seed,status,agent_spec_digest,knowledge_digest,code_digest,"
                "created_by_admin_id) VALUES (:id,:tenant,:suite,:runner,:seed,'RUNNING',"
                ":agent,:knowledge,:code,:admin)"
            ),
            {
                "id": run_id,
                "tenant": self._context.tenant_id,
                "suite": suite_digest,
                "runner": RUNNER_VERSION,
                "seed": request.seed,
                "agent": request.agent_spec_digest,
                "knowledge": request.knowledge_digest,
                "code": request.code_digest,
                "admin": self._context.actor_id,
            },
        )
        started = monotonic()
        summary = await run_cases(cases, seed=request.seed)
        elapsed_ms = int((monotonic() - started) * 1000)
        case_statement = text(
            "INSERT INTO public.eval_case_results (id,tenant_id,eval_run_id,case_id,"
            "passed,grader_results,sanitized_observation,latency_ms) VALUES "
            "(:id,:tenant,:run,:case,:passed,:graders,:observation,:latency)"
        ).bindparams(
            bindparam("graders", type_=JSONB), bindparam("observation", type_=JSONB)
        )
        average_latency = elapsed_ms // max(len(summary.cases), 1)
        for result in summary.cases:
            await self._session.execute(
                case_statement,
                {
                    "id": new_uuid7(),
                    "tenant": self._context.tenant_id,
                    "run": run_id,
                    "case": result.case_id,
                    "passed": result.passed,
                    "graders": [asdict(grade) for grade in result.graders],
                    "observation": redact_artifact(dict(result.observed)),
                    "latency": average_latency,
                },
            )
        inferred_blockers = {
            tag.removeprefix("hard-blocker:")
            for case in cases
            for tag in case.tags
            if tag.startswith("hard-blocker:")
            and not next(
                result for result in summary.cases if result.case_id == case.case_id
            ).passed
        }
        blockers = cast(
            tuple[HardBlocker, ...],
            tuple(sorted(set(request.hard_blockers) | inferred_blockers)),
        )
        complete_suite = set(request.suites) == REQUIRED_PRODUCTION_SUITES
        passed = summary.passed and not blockers and complete_suite
        completed_at = datetime.now(UTC)
        await self._session.execute(
            text(
                "UPDATE public.eval_runs SET status=:status,passed_cases=:passed,"
                "failed_cases=:failed,total_latency_ms=:latency,completed_at=:completed "
                "WHERE tenant_id=:tenant AND id=:id AND status='RUNNING'"
            ),
            {
                "status": "PASSED" if passed else "FAILED",
                "passed": summary.passed_cases,
                "failed": summary.failed_cases,
                "latency": elapsed_ms,
                "completed": completed_at,
                "tenant": self._context.tenant_id,
                "id": run_id,
            },
        )
        decision_id = new_uuid7()
        await self._session.execute(
            text(
                "INSERT INTO public.quality_gate_decisions (id,tenant_id,eval_run_id,"
                "agent_spec_digest,knowledge_digest,code_digest,passed,hard_blockers,"
                "thresholds,decided_at,decided_by_admin_id) VALUES (:id,:tenant,:run,"
                ":agent,:knowledge,:code,:passed,:blockers,:thresholds,:decided,:admin)"
            ).bindparams(bindparam("thresholds", type_=JSONB)),
            {
                "id": decision_id,
                "tenant": self._context.tenant_id,
                "run": run_id,
                "agent": request.agent_spec_digest,
                "knowledge": request.knowledge_digest,
                "code": request.code_digest,
                "passed": passed,
                "blockers": list(blockers),
                "thresholds": {"required_pass_rate": 1.0},
                "decided": completed_at,
                "admin": self._context.actor_id,
            },
        )
        return QualityGateDecision(
            id=decision_id,
            eval_run_id=run_id,
            passed=passed,
            agent_spec_digest=request.agent_spec_digest,
            knowledge_digest=request.knowledge_digest,
            code_digest=request.code_digest,
            hard_blockers=blockers,
            passed_cases=summary.passed_cases,
            failed_cases=summary.failed_cases,
            runner_version=RUNNER_VERSION,
            decided_at=completed_at,
        )

    async def _require_exact_candidate(self, request: QualityGateRunRequest) -> None:
        exists = await self._session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.agent_spec_versions AS agent "
                "WHERE agent.tenant_id=:tenant AND agent.state IN "
                "('TEST','QUALITY_GATE','PRODUCTION') AND "
                "agent.compiled_digest=:agent AND "
                "agent.configuration #>> '{knowledge,digest}'=:knowledge AND "
                "agent.configuration ->> 'code_digest'=:code AND EXISTS(SELECT 1 "
                "FROM public.knowledge_versions AS knowledge WHERE "
                "knowledge.tenant_id=agent.tenant_id AND "
                "knowledge.digest=:knowledge AND knowledge.state IN "
                "('TEST','PRODUCTION')))"
            ),
            {
                "tenant": self._context.tenant_id,
                "agent": request.agent_spec_digest,
                "knowledge": request.knowledge_digest,
                "code": request.code_digest,
            },
        )
        if not exists:
            raise DomainError(
                type="https://agents-factory.dev/problems/eval-candidate-not-found",
                title="Exact Eval Candidate Not Found",
                status=409,
                detail=(
                    "The Production Quality Gate requires an existing tenant-owned "
                    "Test candidate with the exact Agent, Knowledge and code digests."
                ),
                code="eval_candidate_not_found",
            )


def _case_path(name: str) -> Path:
    root = Path(__file__).resolve().parents[6]
    path = root / "evals" / "cases" / f"{name}.jsonl"
    if not path.is_file():
        raise ValueError(f"unknown eval suite: {name}")
    return path
