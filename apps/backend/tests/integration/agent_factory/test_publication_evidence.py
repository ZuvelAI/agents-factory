from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from agents_factory.common.errors import DomainError


@pytest.mark.asyncio
async def test_evidence_requires_success_review_matching_revision_and_digests(
    session_factory,
):
    from test_publication_candidates import configuration, context, seed
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )
    from agents_factory.modules.agent_factory.publication_evidence import (
        PublicationEvidenceService,
        PersistedPanelQualityGate,
    )

    tenant = await seed(session_factory, configuration())
    operation = context(tenant)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        version = await PanelPublicationService(
            session, operation, code_digest="a" * 64
        ).prepare_candidate(expected_revision=1)
        service = PublicationEvidenceService(session, operation, code_digest="a" * 64)
        run = await service.request_tests(version.id)
        queued_job = await session.scalar(
            text(
                "SELECT id FROM public.outbox_jobs WHERE tenant_id=:tenant AND topic='agent.publication.test'"
            ),
            {"tenant": tenant},
        )
        gate = PersistedPanelQualityGate(session, operation)
        values = dict(
            agent_spec_digest=version.compiled_digest,
            knowledge_digest=version.configuration.knowledge.digest,
            code_digest="a" * 64,
        )
        assert await gate.evaluate(**values) is None
        with pytest.raises(DomainError):
            await service.review(run.id, approved=True, expected_revision=1)
    from agent_worker.publication_jobs import handle_publication_test
    from agents_factory.common.queue import JobEnvelope
    from agents_factory.modules.runtime.contracts import AgentTurnResult, RuntimeUsage

    calls = []

    class Runtime:
        async def run(self, turn):
            calls.append(turn)
            return AgentTurnResult(
                "Respuesta para revisión", (), RuntimeUsage(1, 1, 0, 1, 0, 2), None
            )

    envelope = JobEnvelope(
        job_id=queued_job,
        tenant_id=tenant,
        kind="agent.publication.test",
        aggregate_id=run.id,
    )
    for _ in range(2):
        await handle_publication_test(
            envelope=envelope,
            database=SimpleNamespace(session_factory=session_factory),
            runtime=Runtime(),
            code_digest="a" * 64,
        )
    assert len(calls) == 5
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = PublicationEvidenceService(session, operation, code_digest="a" * 64)
        assert (
            await PersistedPanelQualityGate(session, operation).evaluate(**values)
            is None
        )
        await service.review(run.id, approved=True, expected_revision=1)
        assert (
            await PersistedPanelQualityGate(session, operation).evaluate(**values)
            is not None
        )
        assert (
            await PersistedPanelQualityGate(session, operation).evaluate(
                **(values | {"code_digest": "c" * 64})
            )
            is None
        )
        await session.execute(
            text(
                "UPDATE public.tenant_onboarding_configs SET revision=2 WHERE tenant_id=:tenant"
            ),
            {"tenant": tenant},
        )
        assert (
            await PersistedPanelQualityGate(session, operation).evaluate(**values)
            is None
        )


@pytest.mark.asyncio
async def test_failed_rejected_expired_or_cross_tenant_run_never_passes(
    session_factory,
):
    from test_publication_candidates import configuration, context, seed
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )
    from agents_factory.modules.agent_factory.publication_evidence import (
        PublicationEvidenceService,
    )
    from agents_factory.modules.agent_factory.publication_tests import (
        CandidateTestResult,
        ScenarioResult,
    )

    tenant = await seed(session_factory, configuration())
    other = await seed(session_factory, configuration())
    operation = context(tenant)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        version = await PanelPublicationService(
            session, operation, code_digest="a" * 64
        ).prepare_candidate(expected_revision=1)
        service = PublicationEvidenceService(session, operation, code_digest="a" * 64)
        run = await service.request_tests(version.id)
        with pytest.raises(DomainError) as error:
            await PublicationEvidenceService(
                session, context(other), code_digest="a" * 64
            ).read_run(run.id)
        assert error.value.status == 404
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await PublicationEvidenceService(
            session, operation, code_digest="a" * 64
        ).save_result(
            run.id,
            CandidateTestResult(
                scenarios=[
                    ScenarioResult(
                        key="greeting",
                        prompt="Hola",
                        response=None,
                        passed=False,
                        error_code="runtime_error",
                    )
                ],
                checks_passed=False,
            ),
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        with pytest.raises(DomainError):
            await PublicationEvidenceService(
                session, operation, code_digest="a" * 64
            ).review(run.id, approved=True, expected_revision=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_rejected_and_expired_review_never_authorize_publication(
    session_factory, expired
):
    from test_publication_candidates import configuration, context, seed
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )
    from agents_factory.modules.agent_factory.publication_evidence import (
        PublicationEvidenceService,
        PersistedPanelQualityGate,
    )
    from agents_factory.modules.agent_factory.publication_tests import (
        CandidateTestResult,
        ScenarioResult,
    )

    tenant = await seed(session_factory, configuration())
    operation = context(tenant)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        version = await PanelPublicationService(
            session, operation, code_digest="a" * 64
        ).prepare_candidate(expected_revision=1)
        service = PublicationEvidenceService(session, operation, code_digest="a" * 64)
        run = await service.request_tests(version.id)
        run_id = run.id
        if expired:
            run_id = uuid4()
            await session.execute(
                text(
                    "INSERT INTO public.agent_publication_test_runs "
                    "(id,tenant_id,version_id,onboarding_revision,agent_spec_digest,knowledge_digest,code_digest,created_at,expires_at) "
                    "SELECT :new,tenant_id,version_id,onboarding_revision,agent_spec_digest,knowledge_digest,code_digest,"
                    "now()-interval '2 days',now()-interval '1 day' FROM public.agent_publication_test_runs WHERE id=:old"
                ),
                {"new": run_id, "old": run.id},
            )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await PublicationEvidenceService(
            session, operation, code_digest="a" * 64
        ).save_result(
            run_id,
            CandidateTestResult(
                scenarios=[
                    ScenarioResult(
                        key=key, prompt="Prueba", response="Respuesta", passed=True
                    )
                    for key in (
                        "greeting",
                        "known_fact",
                        "unknown_fact",
                        "scope",
                        "injection",
                        "human_control",
                    )
                ],
                checks_passed=True,
            ),
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = PublicationEvidenceService(session, operation, code_digest="a" * 64)
        if expired:
            with pytest.raises(DomainError, match="current"):
                await service.review(run_id, approved=True, expected_revision=1)
        else:
            await service.review(run_id, approved=False, expected_revision=1)
            with pytest.raises(DomainError, match="immutable"):
                await service.review(run_id, approved=True, expected_revision=1)
        assert (
            await PersistedPanelQualityGate(session, operation).evaluate(
                agent_spec_digest=version.compiled_digest,
                knowledge_digest=version.configuration.knowledge.digest,
                code_digest="a" * 64,
            )
            is None
        )


@pytest.mark.asyncio
async def test_repeated_request_reuses_pending_test_and_one_queue_job(session_factory):
    from test_publication_candidates import configuration, context, seed
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )
    from agents_factory.modules.agent_factory.publication_evidence import (
        PublicationEvidenceService,
    )

    tenant = await seed(session_factory, configuration())
    operation = context(tenant)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        version = await PanelPublicationService(
            session, operation, code_digest="a" * 64
        ).prepare_candidate(expected_revision=1)
        service = PublicationEvidenceService(session, operation, code_digest="a" * 64)
        first = await service.request_tests(version.id)
        again = await service.request_tests(version.id)
        assert first.id == again.id
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='agent.publication.test'"
                )
            )
            == 1
        )
