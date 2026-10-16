"""Configuration storage must enforce tenant isolation and optimistic revisions."""

from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest_asyncio.fixture
async def configuration_client(session_factory):
    from agents_factory.common.security import (
        AdminPrincipal,
        PlatformAdminAuthorizer,
        require_platform_admin,
    )
    from agents_factory.dependencies import get_transaction
    from agents_factory.main import create_app

    app = create_app()

    class Verifier:
        async def verify(self, access_jwt):
            return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(Verifier())

    async def admin():
        return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    # Use the actual database role, not the owner, for every HTTP operation.
    async def scoped_transaction():
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            yield session

    app.dependency_overrides[get_transaction] = scoped_transaction
    app.dependency_overrides[require_platform_admin] = admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, app


async def create_company_and_agent(client):
    company = await client.post(
        "/admin/agent-workspace/companies", json={"name": "Zuvel", "slug": str(uuid4())}
    )
    assert company.status_code == 201, company.text
    tenant = company.json()["tenant_id"]
    root = f"/admin/agent-workspace/companies/{tenant}"
    agent = await client.post(root + "/agents", json={"name": "Ventas"})
    assert agent.status_code == 201, agent.text
    return root, agent.json()


@pytest.mark.asyncio
async def test_agents_keep_independent_drafts(configuration_client, session_factory):
    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    second = (await client.post(root + "/agents", json={"name": "Soporte"})).json()
    path = root + f"/agents/{draft['agent_instance_id']}/configuration"
    changed = draft["configuration"]
    changed["purpose"] = "Calificar oportunidades"
    changed["agent"]["instructions"] = "INSTRUCCIONES_PRIVADAS"
    saved = await client.put(
        path, json={"expected_revision": 1, "configuration": changed}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    stale = await client.put(
        path, json={"expected_revision": 1, "configuration": changed}
    )
    assert stale.status_code == 409
    other = (
        await client.get(root + f"/agents/{second['agent_instance_id']}/configuration")
    ).json()
    assert other["configuration"]["purpose"] == "" and other["revision"] == 1
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.agent_spec_versions")
            )
            == 0
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.account_agent_bindings")
            )
            == 0
        )
        payloads = str(
            (await session.execute(text("SELECT payload FROM public.audit_events")))
            .scalars()
            .all()
        )
        assert "INSTRUCCIONES_PRIVADAS" not in payloads


@pytest.mark.asyncio
async def test_workspace_shows_editable_draft_without_fabricating_version(
    configuration_client,
):
    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    agents = (await client.get(root + "/agents")).json()["items"]
    assert agents[0]["display_name"] == "Ventas"
    assert agents[0]["has_pending_changes"] is True
    assert agents[0]["draft_version_id"] is None
    detail = (await client.get(root + f"/agents/{draft['agent_instance_id']}")).json()
    assert detail["draft"]["name"] == "Ventas"
    assert detail["published"] is None
    assert detail["editable_revision"] == 1


@pytest.mark.asyncio
async def test_company_refresh_is_explicit(configuration_client):
    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    profile = (await client.get(root + "/profile")).json()
    profile["configuration"]["business_description"] = "Nueva descripción"
    assert (
        await client.put(
            root + "/profile",
            json={"expected_revision": 1, "configuration": profile["configuration"]},
        )
    ).status_code == 200
    path = root + f"/agents/{draft['agent_instance_id']}/configuration"
    stale = (await client.get(path)).json()
    assert stale["company_update_available"] is True
    assert stale["company_snapshot"]["business_description"] == ""
    assert (
        await client.post(
            path + "/refresh-company",
            json={"expected_revision": 1, "expected_company_revision": 1},
        )
    ).status_code == 409
    refreshed = await client.post(
        path + "/refresh-company",
        json={"expected_revision": 1, "expected_company_revision": 2},
    )
    assert refreshed.status_code == 200, refreshed.text
    assert (
        refreshed.json()["company_snapshot"]["business_description"]
        == "Nueva descripción"
    )
    assert refreshed.json()["revision"] == 2


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_save(configuration_client, monkeypatch):
    from agents_factory.common.audit import AuditService

    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    path = root + f"/agents/{draft['agent_instance_id']}/configuration"

    async def failed_audit(*args, **kwargs):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(AuditService, "record", failed_audit)
    config = draft["configuration"]
    config["purpose"] = "Must roll back"
    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        await client.put(path, json={"expected_revision": 1, "configuration": config})
    stored = (await client.get(path)).json()
    assert stored["revision"] == 1 and stored["configuration"]["purpose"] == ""


@pytest.mark.asyncio
async def test_concurrent_save_returns_conflict(configuration_client):
    import asyncio

    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    path = root + f"/agents/{draft['agent_instance_id']}/configuration"
    first = draft["configuration"]
    import copy

    second = copy.deepcopy(first)
    first["purpose"], second["purpose"] = "Ventas", "Soporte"
    responses = await asyncio.gather(
        *[
            client.put(path, json={"expected_revision": 1, "configuration": config})
            for config in (first, second)
        ]
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert (await client.get(path)).json()["revision"] == 2


@pytest.mark.asyncio
async def test_invalid_model_and_tools_rejected(configuration_client):
    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    path = root + f"/agents/{draft['agent_instance_id']}/configuration"
    config = draft["configuration"]
    config["agent"]["model"] = "unavailable-model"
    assert (
        await client.put(path, json={"expected_revision": 1, "configuration": config})
    ).status_code == 422
    config["agent"]["model"] = "gpt-6-luna"
    config["capabilities"]["selected_capabilities"] = ["appointments"]
    assert (
        await client.put(path, json={"expected_revision": 1, "configuration": config})
    ).status_code == 422


@pytest.mark.asyncio
async def test_unsupported_operation_is_saved_but_reported_as_unavailable(
    configuration_client,
):
    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    config = draft["configuration"]
    config["human_operations"]["handoff_enabled"] = True
    config["knowledge"]["approved_summary"] = "Contenido nuevo sin aprobación"
    config["knowledge"]["review_confirmed"] = False
    response = await client.put(
        root + f"/agents/{draft['agent_instance_id']}/configuration",
        json={"expected_revision": 1, "configuration": config},
    )
    assert response.status_code == 200
    issues = response.json()["validation_issues"]
    assert any(issue["code"] == "unsupported_configuration" for issue in issues)
    assert any(issue["field"] == "knowledge.review_confirmed" for issue in issues)


@pytest.mark.asyncio
async def test_read_and_edit_reject_other_tenant(configuration_client):
    client, app = configuration_client
    root, draft = await create_company_and_agent(client)
    other, _ = await create_company_and_agent(client)
    assert (
        await client.get(other + f"/agents/{draft['agent_instance_id']}/configuration")
    ).status_code == 404
    from agents_factory.common.security import require_platform_admin

    app.dependency_overrides.pop(require_platform_admin)
    assert (await client.get(root + "/profile")).status_code == 401


@pytest.mark.asyncio
async def test_existing_company_profile_created_with_revision_zero(
    configuration_client, session_factory
):
    client, _ = configuration_client
    async with session_factory.begin() as session:
        tenant = uuid4()
        await session.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name) VALUES(:id,:slug,'Anterior')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
    path = f"/admin/agent-workspace/companies/{tenant}/profile"
    assert (await client.get(path)).status_code == 404
    saved = await client.put(
        path,
        json={"expected_revision": 0, "configuration": {"commercial_name": "Actual"}},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert (
        await client.put(
            path,
            json={
                "expected_revision": 0,
                "configuration": {"commercial_name": "Sobrescribir"},
            },
        )
    ).status_code == 409


async def seed_configuration(session):
    tenants, agents = [uuid4(), uuid4()], [uuid4(), uuid4()]
    for tenant, agent in zip(tenants, agents):
        await session.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name) VALUES(:id,:slug,'Empresa')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.agent_instances(id,tenant_id,product) VALUES(:id,:tenant,'Agent Customer Service')"
            ),
            {"id": agent, "tenant": tenant},
        )
        await session.execute(
            text(
                "INSERT INTO public.company_profiles(tenant_id,revision,configuration) VALUES(:tenant,1,'{}')"
            ),
            {"tenant": tenant},
        )
        await session.execute(
            text(
                "INSERT INTO public.agent_configuration_drafts(tenant_id,agent_instance_id,revision,company_revision,company_snapshot,configuration,provenance) VALUES(:tenant,:agent,1,1,'{}','{}','{}')"
            ),
            {"tenant": tenant, "agent": agent},
        )
    return tenants, agents


@pytest.mark.asyncio
async def test_company_and_agent_draft_rls(session_factory):
    async with session_factory.begin() as session:
        tenants, _ = await seed_configuration(session)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await session.execute(
            text("SELECT set_config('app.tenant_id',:tenant,true)"),
            {"tenant": str(tenants[0])},
        )
        for table in ("company_profiles", "agent_configuration_drafts"):
            assert (
                await session.execute(text(f"SELECT tenant_id FROM public.{table}"))
            ).scalars().all() == [tenants[0]]
            assert (
                await session.execute(
                    text(
                        f"UPDATE public.{table} SET revision=2 WHERE tenant_id=:tenant RETURNING tenant_id"
                    ),
                    {"tenant": tenants[1]},
                )
            ).first() is None
    for role in ("agents_factory_app", "anon", "authenticated", "service_role"):
        for table in ("company_profiles", "agent_configuration_drafts"):
            async with session_factory.begin() as session:
                with pytest.raises(DBAPIError, match="permission denied"):
                    await session.execute(text(f"SET LOCAL ROLE {role}"))
                    await session.execute(text(f"SELECT * FROM public.{table}"))


@pytest.mark.asyncio
async def test_draft_fk_rejects_other_tenant(session_factory):
    async with session_factory.begin() as session:
        tenants, agents = await seed_configuration(session)
    async with session_factory.begin() as session:
        with pytest.raises(DBAPIError, match="foreign key"):
            await session.execute(
                text(
                    "INSERT INTO public.agent_configuration_drafts(tenant_id,agent_instance_id,revision,company_revision,company_snapshot,configuration,provenance) VALUES(:tenant,:agent,1,1,'{}','{}','{}')"
                ),
                {"tenant": tenants[0], "agent": agents[1]},
            )


@pytest.mark.asyncio
async def test_draft_compare_and_swap(session_factory):
    from agents_factory.common.context import TenantContext
    from agents_factory.modules.agent_factory.configuration_repository import (
        ConfigurationRepository,
    )

    async with session_factory.begin() as session:
        tenants, agents = await seed_configuration(session)
    context = TenantContext(
        tenant_id=tenants[0],
        actor_id=uuid4(),
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        repository = ConfigurationRepository(session, context)
        first = await repository.update_draft(
            agent_id=agents[0], expected_revision=1, configuration={"purpose": "Ventas"}
        )
        assert first is not None and first["revision"] == 2
        assert (
            await repository.update_draft(
                agent_id=agents[0],
                expected_revision=1,
                configuration={"purpose": "Sobrescritura"},
            )
            is None
        )
        assert (await repository.read_draft(agents[0]))["configuration"] == {
            "purpose": "Ventas"
        }
    async with session_factory() as session:
        repository = ConfigurationRepository(session, context)
        await repository.update_draft(
            agent_id=agents[0],
            expected_revision=2,
            configuration={"purpose": "No guardar"},
        )
        await session.rollback()
    async with session_factory.begin() as session:
        repository = ConfigurationRepository(session, context)
        assert (await repository.read_draft(agents[0]))["configuration"] == {
            "purpose": "Ventas"
        }
