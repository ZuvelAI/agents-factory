from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from agents_factory.common.errors import DomainError
from apps.backend.tests.integration.test_agent_configuration import (
    configuration_client as _client,
)
from apps.backend.tests.integration.test_workspace_publication_candidates import (
    ready_agent,
    prepare,
)
from apps.backend.tests.integration.agent_factory.test_publication_candidates import (
    context,
)

configuration_client = _client


async def request_run(
    session_factory, draft, version, *, kind="SCENARIOS", key=None, messages=None
):
    from agents_factory.modules.agent_factory.publication_evidence import (
        WorkspacePublicationEvidenceService,
    )
    from agents_factory.modules.agent_factory.workspace_publication_models import (
        WorkspaceTestRequest,
    )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        from agents_factory.common.context import TenantContext

        tenant = UUID(draft["tenant_id"])
        actor = TenantContext(tenant, tenant, "platform_admin", uuid4())
        return await WorkspacePublicationEvidenceService(
            session, actor, code_digest="a" * 64
        ).request(
            UUID(draft["agent_instance_id"]),
            version,
            WorkspaceTestRequest(
                run_kind=kind,
                expected_revision=draft["revision"],
                request_key=key or uuid4(),
                messages=messages,
            ),
        )


@pytest.mark.asyncio
async def test_workspace_suite_is_pending_idempotent_and_cannot_be_reviewed_yet(
    configuration_client, session_factory
):
    from agents_factory.modules.agent_factory.publication_evidence import (
        WorkspacePublicationEvidenceService,
    )

    client, _ = configuration_client
    _, draft = await ready_agent(client)
    candidate = await prepare(session_factory, draft)
    key = uuid4()
    one = await request_run(session_factory, draft, candidate.version.id, key=key)
    two = await request_run(session_factory, draft, candidate.version.id, key=key)
    assert one.id == two.id and one.result is None and one.is_current
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = WorkspacePublicationEvidenceService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        )
        with pytest.raises(DomainError) as error:
            await service.review(
                UUID(draft["agent_instance_id"]),
                one.id,
                expected_revision=3,
                approved=True,
                confirm_review=True,
            )
        assert error.value.code == "test_run_not_passed"


@pytest.mark.asyncio
async def test_preview_worker_is_isolated_and_redelivery_reuses_result(
    configuration_client, session_factory
):
    from types import SimpleNamespace
    from agents_factory.common.queue import JobEnvelope
    from agents_factory.modules.runtime.contracts import AgentTurnResult, RuntimeUsage
    from agent_worker.publication_jobs import handle_publication_test
    from agents_factory.modules.agent_factory.publication_evidence import (
        WorkspacePublicationEvidenceService,
    )

    client, _ = configuration_client
    root, draft = await ready_agent(client)
    candidate = await prepare(session_factory, draft)
    run = await request_run(
        session_factory,
        draft,
        candidate.version.id,
        kind="PREVIEW",
        messages=[{"role": "user", "text": "Hola"}],
    )
    async with session_factory.begin() as session:
        job = (
            await session.execute(
                text(
                    "SELECT id FROM public.outbox_jobs WHERE tenant_id=:tenant AND payload->>'test_run_id'=:run"
                ),
                {"tenant": UUID(draft["tenant_id"]), "run": str(run.id)},
            )
        ).scalar_one()
    calls = []

    class Runtime:
        async def run(self, turn):
            calls.append(turn)
            return AgentTurnResult(
                "Hola desde Zuvel", (), RuntimeUsage(1, 1, 0, 1, 0, 2), None
            )

    envelope = JobEnvelope(
        kind="agent.publication.test",
        tenant_id=UUID(draft["tenant_id"]),
        job_id=job,
        aggregate_id=run.id,
    )
    for _ in range(2):
        await handle_publication_test(
            envelope=envelope,
            database=SimpleNamespace(session_factory=session_factory),
            runtime=Runtime(),
            code_digest="a" * 64,
        )
    assert len(calls) == 1 and calls[0].tools == ()
    assert calls[0].trace.tenant_id == UUID(draft["tenant_id"])
    assert calls[0].trace.agent_spec_id == candidate.version.id
    async with session_factory.begin() as session:
        for table in (
            "messages",
            "conversations",
            "outbound_messages",
            "account_agent_bindings",
        ):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = WorkspacePublicationEvidenceService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        )
        result = await service.read(UUID(draft["agent_instance_id"]), run.id)
        assert result.result.response == "Hola desde Zuvel"
        with pytest.raises(DomainError) as error:
            await service.review(
                UUID(draft["agent_instance_id"]),
                run.id,
                expected_revision=3,
                approved=True,
                confirm_review=True,
            )
        assert error.value.code == "preview_not_reviewable"
    config = draft["configuration"]
    config["agent"]["instructions"] = "Instrucciones diferentes"
    await client.put(
        root + f"/agents/{draft['agent_instance_id']}/configuration",
        json={"expected_revision": 3, "configuration": config},
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        result = await WorkspacePublicationEvidenceService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        ).read(UUID(draft["agent_instance_id"]), run.id)
        assert not result.is_current and result.result.response == "Hola desde Zuvel"


@pytest.mark.asyncio
async def test_request_key_reuse_different_content_and_other_agents_run_are_rejected(
    configuration_client, session_factory
):
    from agents_factory.modules.agent_factory.publication_evidence import (
        WorkspacePublicationEvidenceService,
    )

    client, _ = configuration_client
    root, draft = await ready_agent(client)
    candidate = await prepare(session_factory, draft)
    key = uuid4()
    run = await request_run(
        session_factory,
        draft,
        candidate.version.id,
        kind="PREVIEW",
        key=key,
        messages=[{"role": "user", "text": "Hola"}],
    )
    with pytest.raises(DomainError) as error:
        await request_run(
            session_factory,
            draft,
            candidate.version.id,
            kind="PREVIEW",
            key=key,
            messages=[{"role": "user", "text": "Distinto"}],
        )
    assert error.value.code == "test_request_key_conflict"
    with pytest.raises(DomainError) as error:
        await request_run(
            session_factory,
            draft,
            candidate.version.id,
            kind="PREVIEW",
            messages=[{"role": "user", "text": "Otro"}],
        )
    assert error.value.code == "test_run_pending"
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        with pytest.raises(DomainError) as error:
            await WorkspacePublicationEvidenceService(
                session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
            ).read(uuid4(), run.id)
        assert error.value.status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,maximum", [("SCENARIOS", 6), ("PREVIEW", 30)])
async def test_request_limits_are_enforced_by_persisted_runs(
    configuration_client, session_factory, kind, maximum
):
    from agents_factory.modules.agent_factory.publication_evidence import (
        PublicationEvidenceService,
    )
    from agents_factory.modules.agent_factory.publication_preview import PreviewResult
    from agents_factory.modules.agent_factory.publication_tests import (
        CandidateTestResult,
    )

    client, _ = configuration_client
    _, draft = await ready_agent(client)
    candidate = await prepare(session_factory, draft)
    for _ in range(maximum):
        run = await request_run(
            session_factory,
            draft,
            candidate.version.id,
            kind=kind,
            messages=[{"role": "user", "text": "Hola"}] if kind == "PREVIEW" else None,
        )
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await PublicationEvidenceService(
                session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
            ).save_result(
                run.id,
                PreviewResult(error_code="failed")
                if kind == "PREVIEW"
                else CandidateTestResult(scenarios=[], checks_passed=False),
            )
    with pytest.raises(DomainError) as error:
        await request_run(
            session_factory,
            draft,
            candidate.version.id,
            kind=kind,
            messages=[{"role": "user", "text": "Hola"}] if kind == "PREVIEW" else None,
        )
    assert error.value.status == 429


@pytest.mark.asyncio
async def test_worker_suite_can_be_reviewed_but_never_through_legacy_route(
    configuration_client, session_factory, monkeypatch
):
    from types import SimpleNamespace
    from agents_factory.common.queue import JobEnvelope
    from agents_factory.common.audit import AuditService
    from agents_factory.modules.runtime.contracts import AgentTurnResult, RuntimeUsage
    from agent_worker.publication_jobs import handle_publication_test
    from agents_factory.modules.agent_factory.publication_evidence import (
        PublicationEvidenceService,
        WorkspacePublicationEvidenceService,
    )

    client, _ = configuration_client
    _, draft = await ready_agent(client)
    candidate = await prepare(session_factory, draft)
    run = await request_run(session_factory, draft, candidate.version.id)
    calls = []

    class Runtime:
        async def run(self, turn):
            calls.append(turn)
            return AgentTurnResult(
                "Respuesta para revisión", (), RuntimeUsage(1, 1, 0, 1, 0, 2), None
            )

    async with session_factory.begin() as session:
        job = await session.scalar(
            text(
                "SELECT id FROM public.outbox_jobs WHERE payload->>'test_run_id'=:run"
            ),
            {"run": str(run.id)},
        )
    await handle_publication_test(
        envelope=JobEnvelope(
            job, UUID(draft["tenant_id"]), "agent.publication.test", run.id
        ),
        database=SimpleNamespace(session_factory=session_factory),
        runtime=Runtime(),
        code_digest="a" * 64,
    )
    assert len(calls) == 5 and all(turn.tools == () for turn in calls)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        legacy = PublicationEvidenceService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        )
        with pytest.raises(DomainError) as error:
            await legacy.review(run.id, approved=True, expected_revision=3)
        assert error.value.status == 404

    async def audit_down(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(AuditService, "record", audit_down)
        with pytest.raises(RuntimeError):
            async with session_factory.begin() as session:
                await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
                await WorkspacePublicationEvidenceService(
                    session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
                ).review(
                    UUID(draft["agent_instance_id"]),
                    run.id,
                    expected_revision=3,
                    approved=True,
                    confirm_review=True,
                )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.agent_publication_reviews")
            )
            == 0
        )
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        reviewed = await WorkspacePublicationEvidenceService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        ).review(
            UUID(draft["agent_instance_id"]),
            run.id,
            expected_revision=3,
            approved=True,
            confirm_review=True,
        )
        assert reviewed.approved and reviewed.result.checks_passed
