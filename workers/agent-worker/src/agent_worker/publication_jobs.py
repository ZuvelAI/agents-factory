from datetime import UTC, datetime

from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import JobEnvelope
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.agent_factory.publication_evidence import (
    PublicationEvidenceService,
)
from agents_factory.modules.agent_factory.publication_tests import (
    CandidateTestResult,
    ScenarioResult,
    run_candidate_tests,
)
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.runtime.contracts import AgentRuntime
from agents_factory.modules.runtime.contracts import TurnMessage
from agents_factory.modules.agent_factory.publication_preview import (
    PreviewResult,
    run_candidate_preview,
)
from uuid import uuid4


async def handle_publication_test(
    *,
    envelope: JobEnvelope,
    database: Database,
    runtime: AgentRuntime,
    code_digest: str | None,
) -> None:
    if envelope.kind != "agent.publication.test":
        raise ValueError("unexpected publication job kind")
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        payload = await session.scalar(
            text(
                "SELECT payload FROM public.outbox_jobs "
                "WHERE tenant_id=:tenant AND id=:job AND topic='agent.publication.test'"
            ),
            {"tenant": envelope.tenant_id, "job": envelope.job_id},
        )
        if not isinstance(payload, dict) or payload.get("test_run_id") != str(
            envelope.aggregate_id
        ):
            raise ValueError("publication job payload mismatch")
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"publication:{envelope.tenant_id}:{envelope.aggregate_id}"},
        )
        context = TenantContext(
            tenant_id=envelope.tenant_id,
            actor_id=None,
            actor_type="system",
            correlation_id=envelope.job_id,
        )
        service = PublicationEvidenceService(session, context, code_digest=code_digest)
        run = await service.read_run(envelope.aggregate_id, check_current=False)
        if run.result is not None:
            return
        version = await AgentSpecRepository(session, context).get_version(
            run.version_id
        )
        if (
            version is None
            or version.compiled_spec is None
            or version.compiled_spec.digest() != run.agent_spec_digest
            or version.configuration.knowledge.digest != run.knowledge_digest
            or run.code_digest != code_digest
            or run.expires_at <= datetime.now(UTC)
        ):
            result: CandidateTestResult | PreviewResult = (
                PreviewResult(error_code="candidate_integrity_failed")
                if run.run_kind == "PREVIEW"
                else CandidateTestResult(
                    scenarios=[
                        ScenarioResult(
                            key="integrity",
                            prompt="Verificar candidato",
                            passed=False,
                            error_code="candidate_integrity_failed",
                        )
                    ],
                    checks_passed=False,
                )
            )
        elif run.run_kind == "PREVIEW":
            result = await run_candidate_preview(
                version.compiled_spec,
                tuple(
                    TurnMessage(uuid4(), m.role, m.text)
                    for m in (run.input_messages or [])
                ),
                runtime,
            )
        else:
            result = await run_candidate_tests(version.compiled_spec, runtime)
        await service.save_result(run.id, result)
