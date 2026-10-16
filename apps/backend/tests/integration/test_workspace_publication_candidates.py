from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agents_factory.common.errors import DomainError
from apps.backend.tests.integration.test_agent_configuration import (
    configuration_client as _configuration_client,
    create_company_and_agent,
)
from apps.backend.tests.integration.agent_factory.test_publication_candidates import (
    configuration,
    context,
)

configuration_client = _configuration_client


async def ready_agent(client):
    root, draft = await create_company_and_agent(client)
    source = configuration().model_dump(mode="json")
    profile = (await client.get(root + "/profile")).json()
    saved = await client.put(
        root + "/profile",
        json={
            "expected_revision": profile["revision"],
            "configuration": source.pop("company"),
        },
    )
    assert saved.status_code == 200, saved.text
    refreshed = await client.post(
        root + f"/agents/{draft['agent_instance_id']}/configuration/refresh-company",
        json={"expected_revision": 1, "expected_company_revision": 2},
    )
    assert refreshed.status_code == 200, refreshed.text
    config = refreshed.json()["configuration"]
    config.update(
        {
            key: value
            for key, value in source.items()
            if key in config and key not in {"capabilities", "integrations"}
        }
    )
    config["purpose"] = "Calificar oportunidades sin inventar precios"
    result = await client.put(
        root + f"/agents/{draft['agent_instance_id']}/configuration",
        json={"expected_revision": 2, "configuration": config},
    )
    assert result.status_code == 200, result.text
    return root, result.json()


async def prepare(session_factory, draft):
    from agents_factory.modules.agent_factory.workspace_publication_service import (
        WorkspacePublicationService,
    )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return await WorkspacePublicationService(
            session, context(UUID(draft["tenant_id"])), code_digest="a" * 64
        ).prepare(
            agent_id=UUID(draft["agent_instance_id"]),
            expected_revision=draft["revision"],
            expected_company_revision=draft["company_revision"],
        )


@pytest.mark.asyncio
async def test_candidate_is_exact_idempotent_and_keeps_existing_instance(
    configuration_client, session_factory
):
    client, _ = configuration_client
    root, draft = await ready_agent(client)
    first = await prepare(session_factory, draft)
    same = await prepare(session_factory, draft)
    assert first.version.id == same.version.id
    assert str(first.version.agent_instance_id) == draft["agent_instance_id"]
    assert first.version.state == "TEST"
    assert first.version.based_on_version_id is None
    assert (
        draft["configuration"]["purpose"]
        in first.version.configuration.persona.instructions
    )
    async with session_factory.begin() as session:
        for table in (
            "account_agent_bindings",
            "panel_agent_candidates",
            "tenant_onboarding_configs",
        ):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )
        assert (
            await session.scalar(text("SELECT count(*) FROM public.agent_instances"))
            == 1
        )
    current = (
        await client.get(root + f"/agents/{draft['agent_instance_id']}/configuration")
    ).json()
    assert current == draft


@pytest.mark.asyncio
async def test_two_agents_with_same_revision_never_share_candidate(
    configuration_client, session_factory
):
    client, _ = configuration_client
    root, first = await ready_agent(client)
    other = (await client.post(root + "/agents", json={"name": "Soporte"})).json()
    other = (
        await client.put(
            root + f"/agents/{other['agent_instance_id']}/configuration",
            json={"expected_revision": 1, "configuration": first["configuration"]},
        )
    ).json()
    # Reach the same revision without modifying its semantics.
    other = (
        await client.put(
            root + f"/agents/{other['agent_instance_id']}/configuration",
            json={"expected_revision": 2, "configuration": other["configuration"]},
        )
    ).json()
    assert other["revision"] == first["revision"]
    one, two = (
        await prepare(session_factory, first),
        await prepare(session_factory, other),
    )
    assert one.version.id != two.version.id
    assert one.version.agent_instance_id != two.version.agent_instance_id


@pytest.mark.asyncio
async def test_stale_company_and_draft_cannot_prepare(
    configuration_client, session_factory
):
    client, _ = configuration_client
    root, draft = await ready_agent(client)
    stale = dict(draft, revision=1)
    with pytest.raises(DomainError) as error:
        await prepare(session_factory, stale)
    assert error.value.status == 409
    profile = (await client.get(root + "/profile")).json()
    await client.put(
        root + "/profile",
        json={"expected_revision": 2, "configuration": profile["configuration"]},
    )
    with pytest.raises(DomainError) as error:
        await prepare(session_factory, draft)
    assert error.value.code == "company_snapshot_stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
async def test_candidate_metadata_is_immutable(
    configuration_client, session_factory, operation
):
    client, _ = configuration_client
    _, draft = await ready_agent(client)
    await prepare(session_factory, draft)
    statement = (
        "UPDATE public.workspace_agent_candidates SET draft_revision=99"
        if operation == "UPDATE"
        else "DELETE FROM public.workspace_agent_candidates"
    )
    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(text(statement))


@pytest.mark.asyncio
async def test_candidate_read_is_tenant_scoped_and_app_cannot_insert(
    configuration_client, session_factory
):
    client, _ = configuration_client
    _, draft = await ready_agent(client)
    await prepare(session_factory, draft)
    from uuid import uuid4

    for role in ("agents_factory_admin", "agents_factory_app"):
        async with session_factory.begin() as session:
            await session.execute(text(f"SET LOCAL ROLE {role}"))
            await session.execute(
                text("SELECT set_config('app.tenant_id',:tenant,true)"),
                {"tenant": str(uuid4())},
            )
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM public.workspace_agent_candidates")
                )
                == 0
            )
            await session.execute(
                text("SELECT set_config('app.tenant_id',:tenant,true)"),
                {"tenant": draft["tenant_id"]},
            )
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM public.workspace_agent_candidates")
                )
                == 1
            )
    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await session.execute(
                text(
                    "INSERT INTO public.workspace_agent_candidates SELECT * FROM public.workspace_agent_candidates"
                )
            )


@pytest.mark.asyncio
async def test_concurrent_preparation_returns_one_candidate(
    configuration_client, session_factory
):
    import asyncio

    client, _ = configuration_client
    _, draft = await ready_agent(client)
    first, second = await asyncio.gather(
        prepare(session_factory, draft), prepare(session_factory, draft)
    )
    assert first.version.id == second.version.id
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.agent_spec_versions")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_candidate_audit_failure_rolls_back_every_new_snapshot(
    configuration_client, session_factory, monkeypatch
):
    from agents_factory.common.audit import AuditService

    client, _ = configuration_client
    _, draft = await ready_agent(client)

    async def unavailable(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditService, "record", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await prepare(session_factory, draft)
    async with session_factory.begin() as session:
        for table in (
            "workspace_agent_candidates",
            "agent_spec_versions",
            "agent_approved_knowledge_versions",
        ):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )


@pytest.mark.asyncio
async def test_wrong_instance_fk_cannot_attach_another_agents_version(
    configuration_client, session_factory
):
    from uuid import uuid4

    client, _ = configuration_client
    root, draft = await ready_agent(client)
    candidate = await prepare(session_factory, draft)
    other = (await client.post(root + "/agents", json={"name": "Otro"})).json()
    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO public.workspace_agent_candidates (tenant_id,agent_instance_id,draft_revision,company_revision,source_digest,code_digest,version_id) VALUES(:tenant,:agent,1,1,:digest,:digest,:version)"
                ),
                {
                    "tenant": UUID(draft["tenant_id"]),
                    "agent": UUID(other["agent_instance_id"]),
                    "digest": "b" * 64,
                    "version": candidate.version.id,
                },
            )
    # Another tenant's instance also remains inaccessible through application service.
    with pytest.raises(DomainError) as error:
        await prepare(session_factory, dict(draft, agent_instance_id=str(uuid4())))
    assert error.value.status == 404


@pytest.mark.asyncio
async def test_candidate_rejects_missing_code_and_incomplete_configuration(
    configuration_client, session_factory
):
    from agents_factory.modules.agent_factory.workspace_publication_service import (
        WorkspacePublicationService,
    )

    client, _ = configuration_client
    _, draft = await ready_agent(client)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = WorkspacePublicationService(
            session, context(UUID(draft["tenant_id"])), code_digest=None
        )
        with pytest.raises(DomainError) as error:
            await service.prepare(
                agent_id=UUID(draft["agent_instance_id"]),
                expected_revision=3,
                expected_company_revision=2,
            )
        assert error.value.code == "publication_code_missing"
    root, incomplete = await create_company_and_agent(client)
    with pytest.raises(DomainError) as error:
        await prepare(session_factory, incomplete)
    assert error.value.code == "publication_configuration_incomplete"
