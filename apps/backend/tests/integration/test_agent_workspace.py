from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from agents_factory.common.security import (
    AdminPrincipal,
    PlatformAdminAuthorizer,
    require_platform_admin,
)
from agents_factory.dependencies import TransactionSession, get_transaction
from agents_factory.main import create_app


@pytest_asyncio.fixture
async def workspace(session_factory):
    tenants = [uuid4() for _ in range(3)]
    agents = []
    async with session_factory.begin() as session:
        for tenant in tenants:
            await session.execute(
                text(
                    "INSERT INTO public.tenants(id,slug,name) VALUES(:id,:slug,'Empresa homónima')"
                ),
                {"id": tenant, "slug": str(tenant)},
            )
        for index in range(5):
            tenant = tenants[1] if index == 0 else tenants[2]
            agent, version = uuid4(), uuid4()
            agents.append(agent)
            await session.execute(
                text(
                    "INSERT INTO public.agent_instances(id,tenant_id,product) VALUES(:id,:tenant,'Agent Customer Service')"
                ),
                {"id": agent, "tenant": tenant},
            )
            await session.execute(
                text(
                    "INSERT INTO public.agent_spec_versions(id,tenant_id,agent_instance_id,version_number,state,configuration) VALUES(:id,:tenant,:agent,1,'DRAFT',:config)"
                ).bindparams(bindparam("config", type_=JSONB)),
                {
                    "id": version,
                    "tenant": tenant,
                    "agent": agent,
                    "config": {
                        "persona": {
                            "business_name": f"Agente {index}",
                            "instructions": "Información empresarial",
                        },
                        "model": {"model": "gpt-6-luna"},
                        "access_token": "SENSITIVE_FIXTURE",
                        "capabilities": [],
                        "connector_bindings": [],
                    },
                },
            )
    app = create_app()

    class Verifier:
        async def verify(self, access_jwt):
            return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(Verifier())

    async def transaction() -> AsyncIterator:
        async with session_factory.begin() as session:
            yield session

    async def admin(session: TransactionSession):
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.dependency_overrides[get_transaction] = transaction
    app.dependency_overrides[require_platform_admin] = admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, tenants, agents, app


@pytest.mark.asyncio
async def test_companies_show_real_counts_and_bounded_agent_preview(workspace):
    client, tenants, agents, _ = workspace
    response = await client.get("/admin/agent-workspace/companies")
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["items"]}
    assert [rows[str(t)]["agent_count"] for t in tenants] == [0, 1, 4]
    assert len(rows[str(tenants[2])]["agents"]) == 3
    assert "SENSITIVE_FIXTURE" not in response.text
    assert "access_token" not in response.text


@pytest.mark.asyncio
async def test_agents_paginate_without_duplicates_and_reject_invalid_cursor(workspace):
    client, tenants, _, _ = workspace
    path = f"/admin/agent-workspace/companies/{tenants[2]}/agents"
    first = await client.get(path, params={"limit": 2})
    assert first.status_code == 200
    second = await client.get(
        path, params={"limit": 2, "cursor": first.json()["next_cursor"]}
    )
    assert second.status_code == 200
    ids = [a["id"] for a in first.json()["items"] + second.json()["items"]]
    assert len(ids) == len(set(ids)) == 4
    assert second.json()["next_cursor"] is None
    assert (await client.get(path, params={"cursor": "garbage"})).status_code == 422
    assert (await client.get(path, params={"limit": 51})).status_code == 422


@pytest.mark.asyncio
async def test_agent_detail_does_not_publish_draft_or_leak_credentials(
    workspace, session_factory
):
    client, tenants, agents, _ = workspace
    async with session_factory.begin() as session:
        before = await session.scalar(text("SELECT count(*) FROM public.audit_events"))
    response = await client.get(
        f"/admin/agent-workspace/companies/{tenants[1]}/agents/{agents[0]}"
    )
    assert response.status_code == 200
    value = response.json()
    assert value["published"] is None
    assert value["draft"]["name"] == "Agente 0"
    assert value["draft"]["tone"] is None
    assert value["summary"]["execution_status"] == "unassigned"
    assert "SENSITIVE_FIXTURE" not in response.text
    async with session_factory.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.audit_events"))
            == before
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.agent_spec_versions")
            )
            == 5
        )


@pytest.mark.asyncio
async def test_detail_rejects_cross_tenant_agent_and_unknown_company(workspace):
    client, tenants, agents, _ = workspace
    assert (
        await client.get(
            f"/admin/agent-workspace/companies/{tenants[0]}/agents/{agents[0]}"
        )
    ).status_code == 404
    assert (
        await client.get(f"/admin/agent-workspace/companies/{uuid4()}/agents")
    ).status_code == 404


@pytest.mark.asyncio
async def test_company_search_and_cursor_preserve_duplicate_names(workspace):
    client, tenants, _, _ = workspace
    first = await client.get(
        "/admin/agent-workspace/companies", params={"limit": 1, "query": "homónima"}
    )
    assert first.status_code == 200
    seen = [first.json()["items"][0]["id"]]
    cursor = first.json()["next_cursor"]
    while cursor:
        page = await client.get(
            "/admin/agent-workspace/companies",
            params={"limit": 1, "cursor": cursor, "query": "homónima"},
        )
        seen.extend(row["id"] for row in page.json()["items"])
        cursor = page.json()["next_cursor"]
    assert set(map(UUID, seen)) == set(tenants)
    assert len(seen) == 3
    empty = await client.get(
        "/admin/agent-workspace/companies", params={"query": "no existe"}
    )
    assert empty.json()["items"] == []


@pytest.mark.asyncio
async def test_workspace_requires_admin(workspace):
    client, _, _, app = workspace
    app.dependency_overrides.pop(require_platform_admin)
    assert (await client.get("/admin/agent-workspace/companies")).status_code == 401
    denied = await client.get(
        "/admin/agent-workspace/companies",
        headers={"Authorization": "Bearer not-admin"},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_workspace_conversations_filter_by_persisted_message_not_account_binding(
    workspace, session_factory
):
    client, tenants, agents, _ = workspace
    tenant, agent = tenants[1], agents[0]
    account_id, first, second = uuid4(), uuid4(), uuid4()
    async with session_factory.begin() as session:
        version = await session.scalar(
            text(
                "SELECT id FROM public.agent_spec_versions WHERE tenant_id=:tenant AND agent_instance_id=:agent"
            ),
            {"tenant": tenant, "agent": agent},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts(id,tenant_id,provider,waba_id,phone_number_id) VALUES(:id,:tenant,'meta','waba','phone')"
            ),
            {"id": account_id, "tenant": tenant},
        )
        for conversation in [first, second]:
            await session.execute(
                text(
                    "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES(:id,:tenant,:account,:customer)"
                ),
                {
                    "id": conversation,
                    "tenant": tenant,
                    "account": account_id,
                    "customer": str(conversation),
                },
            )
        for sequence in range(1, 4):
            await session.execute(
                text(
                    "INSERT INTO public.messages(id,tenant_id,conversation_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence,agent_spec_id) VALUES(:id,:tenant,:conversation,'outbound','ai','text','{\"text\":\"Respuesta guardada\"}',now(),:sequence,:version)"
                ),
                {
                    "id": uuid4(),
                    "tenant": tenant,
                    "conversation": first,
                    "sequence": sequence,
                    "version": version,
                },
            )
    root = f"/admin/agent-workspace/companies/{tenant}/conversations"
    listed = await client.get(
        root, params={"agent_id": str(agent), "account_id": str(account_id)}
    )
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()["items"]] == [str(first)]
    assert listed.json()["items"][0]["agent_ids"] == [str(agent)]
    unfiltered = await client.get(root)
    unknown = next(r for r in unfiltered.json()["items"] if r["id"] == str(second))
    assert unknown["agent_ids"] == []
    path = f"{root}/{first}/messages"
    page = await client.get(path, params={"limit": 2})
    assert page.status_code == 200
    assert [m["arrival_sequence"] for m in page.json()["items"]] == [2, 3]
    assert all(
        m["agent_id"] == str(agent) and m["agent_spec_id"] == str(version)
        for m in page.json()["items"]
    )
    older = await client.get(
        path, params={"limit": 2, "cursor": page.json()["next_cursor"]}
    )
    assert [m["arrival_sequence"] for m in older.json()["items"]] == [1]
    assert older.json()["next_cursor"] is None
    assert (
        await client.get(path, params={"cursor": "not-a-cursor"})
    ).status_code == 422
    denied = await client.get(
        f"/admin/agent-workspace/companies/{tenants[0]}/conversations/{first}/messages"
    )
    assert denied.status_code == 404
    assert (
        await client.get(root, params={"agent_id": str(agents[1])})
    ).status_code == 404
    async with session_factory.begin() as session:
        # A later account health/change cannot relabel the stored response's version.
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET health_status='ERROR' WHERE id=:id"
            ),
            {"id": account_id},
        )
    again = await client.get(path)
    assert {m["agent_id"] for m in again.json()["items"]} == {str(agent)}


@pytest.mark.asyncio
async def test_published_snapshot_is_separate_from_later_draft_and_channel_health(
    workspace, session_factory
):
    from apps.backend.tests.integration.agent_factory.test_publication_candidates import (
        configuration,
        context,
        seed,
    )
    from apps.backend.tests.integration.agent_factory.test_channel_publication import (
        account,
        prepare_reviewed,
    )
    from agents_factory.modules.agent_factory.publication_service import (
        PanelPublicationService,
    )
    from agents_factory.modules.agent_factory.repository import AgentSpecRepository
    from agents_factory.modules.agent_factory.models import PersonaConfiguration

    client, _, _, _ = workspace
    tenant = await seed(session_factory, configuration())
    operation = context(tenant)
    selected = await account(session_factory, tenant)
    version, run = await prepare_reviewed(session_factory, tenant, operation)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await PanelPublicationService(session, operation, code_digest="a" * 64).publish(
            version_id=version.id,
            whatsapp_account_id=selected,
            expected_revision=1,
            test_run_id=run.id,
            expected_binding_revision=0,
        )
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET last_health_checked_at=now() WHERE id=:id"
            ),
            {"id": selected},
        )
        config = version.configuration.model_copy(
            update={
                "persona": PersonaConfiguration(
                    version="2",
                    business_name="Nuevo nombre",
                    instructions="Nuevo borrador",
                )
            }
        )
        await AgentSpecRepository(session, operation).create_draft(
            agent_instance_id=version.agent_instance_id,
            configuration=config,
            based_on_version_id=version.id,
        )
    response = await client.get(
        f"/admin/agent-workspace/companies/{tenant}/agents/{version.agent_instance_id}"
    )
    assert response.status_code == 200
    value = response.json()
    assert value["published"]["name"] == "Zuvel"
    assert value["draft"]["name"] == "Nuevo nombre"
    assert value["summary"]["display_name"] == "Zuvel"
    assert value["summary"]["published_version_id"] == str(version.id)
    assert value["summary"]["has_pending_changes"] is True
    assert value["summary"]["execution_status"] == "unknown"
    assert value["summary"]["channel_accounts"][0]["connection_status"] == "connected"
