from uuid import UUID
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
from apps.backend.tests.integration.test_workspace_publication_evidence import (
    request_run,
)
from apps.backend.tests.integration.agent_factory.test_publication_candidates import (
    context,
)
from apps.backend.tests.integration.agent_factory.test_channel_publication import (
    account,
)

configuration_client = _client


async def reviewed_candidate(session_factory, draft):
    from agents_factory.modules.agent_factory.publication_evidence import (
        PublicationEvidenceService,
        WorkspacePublicationEvidenceService,
    )
    from agents_factory.modules.agent_factory.publication_tests import (
        CandidateTestResult,
        ScenarioResult,
    )

    candidate = await prepare(session_factory, draft)
    run = await request_run(session_factory, draft, candidate.version.id)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await PublicationEvidenceService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        ).save_result(
            run.id,
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
        await WorkspacePublicationEvidenceService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        ).review(
            UUID(draft["agent_instance_id"]),
            run.id,
            expected_revision=draft["revision"],
            approved=True,
            confirm_review=True,
        )
    return candidate, run


async def publish(
    session_factory, draft, candidate, run, selected, revision=0, current_agent=None
):
    from agents_factory.modules.agent_factory.workspace_publication_service import (
        WorkspacePublicationService,
    )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return await WorkspacePublicationService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        ).publish(
            agent_id=UUID(draft["agent_instance_id"]),
            expected_revision=draft["revision"],
            version_id=candidate.version.id,
            test_run_id=run.id,
            whatsapp_account_id=selected,
            expected_binding_revision=revision,
            expected_current_agent_id=current_agent,
            confirm_publish=True,
        )


@pytest.mark.asyncio
async def test_publish_and_rollback_preserve_other_accounts_and_draft(
    configuration_client, session_factory
):
    from agents_factory.modules.agent_factory.workspace_publication_service import (
        WorkspacePublicationService,
    )

    client, _ = configuration_client
    root, draft = await ready_agent(client)
    selected = await account(session_factory, UUID(draft["tenant_id"]))
    first, run = await reviewed_candidate(session_factory, draft)
    binding = await publish(session_factory, draft, first, run, selected)
    assert binding.version_id == first.version.id and binding.revision == 1
    config = draft["configuration"]
    config["agent"]["instructions"] = "Nueva respuesta aprobada"
    updated = (
        await client.put(
            root + f"/agents/{draft['agent_instance_id']}/configuration",
            json={"expected_revision": 3, "configuration": config},
        )
    ).json()
    second, run2 = await reviewed_candidate(session_factory, updated)
    binding = await publish(
        session_factory,
        updated,
        second,
        run2,
        selected,
        1,
        UUID(draft["agent_instance_id"]),
    )
    assert binding.revision == 2
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        binding = await WorkspacePublicationService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        ).rollback(
            agent_id=UUID(draft["agent_instance_id"]),
            whatsapp_account_id=selected,
            target_version_id=first.version.id,
            expected_binding_revision=2,
            confirm_rollback=True,
        )
        assert binding.version_id == first.version.id and binding.revision == 3
    current = (
        await client.get(root + f"/agents/{draft['agent_instance_id']}/configuration")
    ).json()
    assert (
        current["revision"] == 4
        and current["configuration"]["agent"]["instructions"]
        == "Nueva respuesta aprobada"
    )


@pytest.mark.asyncio
async def test_publication_route_is_scoped_and_confirms_destination(
    configuration_client, session_factory
):
    from types import SimpleNamespace

    client, app = configuration_client
    app.state.settings = SimpleNamespace(
        agent_publication_code_digest="a" * 64, agent_publication_compatible_versions={}
    )
    root, draft = await ready_agent(client)
    selected = await account(session_factory, UUID(draft["tenant_id"]))
    candidate, run = await reviewed_candidate(session_factory, draft)
    path = root + f"/agents/{draft['agent_instance_id']}/publication"
    response = await client.get(path)
    assert response.status_code == 200, response.text
    assert response.json()["candidates"][0]["version"]["id"] == str(
        candidate.version.id
    )
    payload = {
        "expected_revision": 3,
        "version_id": str(candidate.version.id),
        "test_run_id": str(run.id),
        "whatsapp_account_id": str(selected),
        "expected_binding_revision": 0,
        "expected_current_agent_id": None,
        "confirm_publish": False,
    }
    response = await client.post(path + "/publish", json=payload)
    assert response.status_code == 422
    payload["confirm_publish"] = True
    response = await client.post(path + "/publish", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["version_id"] == str(candidate.version.id)


@pytest.mark.asyncio
async def test_unreviewed_stale_or_mismatched_binding_cannot_publish(
    configuration_client, session_factory
):
    client, _ = configuration_client
    root, draft = await ready_agent(client)
    selected = await account(session_factory, UUID(draft["tenant_id"]))
    candidate = await prepare(session_factory, draft)
    run = await request_run(session_factory, draft, candidate.version.id)
    with pytest.raises(DomainError):
        await publish(session_factory, draft, candidate, run, selected)
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.account_agent_bindings")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_concurrent_publications_only_one_binding_wins(
    configuration_client, session_factory
):
    import asyncio

    client, _ = configuration_client
    root, draft = await ready_agent(client)
    other = (await client.post(root + "/agents", json={"name": "Soporte"})).json()
    other = (
        await client.put(
            root + f"/agents/{other['agent_instance_id']}/configuration",
            json={"expected_revision": 1, "configuration": draft["configuration"]},
        )
    ).json()
    one, run_one = await reviewed_candidate(session_factory, draft)
    two, run_two = await reviewed_candidate(session_factory, other)
    selected = await account(session_factory, UUID(draft["tenant_id"]))
    results = await asyncio.gather(
        publish(session_factory, draft, one, run_one, selected),
        publish(session_factory, other, two, run_two, selected),
        return_exceptions=True,
    )
    assert (
        len(
            [
                r
                for r in results
                if isinstance(r, DomainError) and r.code == "stale_account_binding"
            ]
        )
        == 1
    )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT revision FROM public.account_agent_bindings")
            )
            == 1
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.agent_spec_deployments WHERE action='PUBLISH'"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_publication_audit_failure_rolls_back_version_binding_and_history(
    configuration_client, session_factory, monkeypatch
):
    from agents_factory.common.audit import AuditService

    client, _ = configuration_client
    _, draft = await ready_agent(client)
    candidate, run = await reviewed_candidate(session_factory, draft)
    selected = await account(session_factory, UUID(draft["tenant_id"]))

    async def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditService, "record", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await publish(session_factory, draft, candidate, run, selected)
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT state FROM public.agent_spec_versions WHERE id=:id"),
                {"id": candidate.version.id},
            )
            == "TEST"
        )
        for table in (
            "account_agent_bindings",
            "account_agent_binding_history",
            "agent_spec_deployments",
        ):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )


@pytest.mark.asyncio
async def test_expired_evidence_cannot_publish_even_when_approved(
    configuration_client, session_factory, monkeypatch
):
    from datetime import datetime, timedelta
    import agents_factory.modules.agent_factory.publication_evidence as evidence

    client, _ = configuration_client
    _, draft = await ready_agent(client)
    candidate, run = await reviewed_candidate(session_factory, draft)
    selected = await account(session_factory, UUID(draft["tenant_id"]))

    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=2)

    monkeypatch.setattr(evidence, "datetime", Future)
    with pytest.raises(DomainError) as error:
        await publish(session_factory, draft, candidate, run, selected)
    assert error.value.code == "production_quality_gate_required"


@pytest.mark.asyncio
async def test_agent_edit_and_changed_company_invalidate_reviewed_publication(
    configuration_client, session_factory
):
    client, _ = configuration_client
    root, draft = await ready_agent(client)
    candidate, run = await reviewed_candidate(session_factory, draft)
    selected = await account(session_factory, UUID(draft["tenant_id"]))
    profile = (await client.get(root + "/profile")).json()
    profile["configuration"]["commercial_name"] = "Nombre actualizado"
    await client.put(
        root + "/profile",
        json={"expected_revision": 2, "configuration": profile["configuration"]},
    )
    with pytest.raises(DomainError) as error:
        await publish(session_factory, draft, candidate, run, selected)
    assert error.value.code == "company_snapshot_stale"
