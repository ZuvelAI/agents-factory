"""Administrative reads remain bounded, scoped and tied to immutable evidence."""

from uuid import uuid4

from sqlalchemy import text
from agents_factory.common.security import require_platform_admin
from apps.backend.tests.integration.test_agent_configuration import (
    configuration_client as _configuration_client,
)
from apps.backend.tests.integration.test_lead_capture import seed, inbound, capture

configuration_client = _configuration_client


async def prospect(factory, world=None):
    world = world or await seed(factory)
    result = await capture(
        factory,
        world,
        await inbound(factory, world),
        declared_name="Ana",
        declared_company="Nexo",
        service_interest="Agente de ventas",
        need_summary="Automatizar ventas",
    )
    return world, result.prospect_id


async def test_reads_search_identity_company_and_evidence(
    configuration_client, session_factory
):
    client, _ = configuration_client
    world, identity = await prospect(session_factory)
    root = f"/admin/agent-workspace/companies/{world[0].tenant_id}"
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.lead_prospects SET contact_username='ana.ventas' WHERE id=:id"
            ),
            {"id": identity},
        )
    for query in ("Ana", "Nexo", "573000000001", "ana.ventas"):
        response = await client.get(root + "/prospects", params={"q": query})
        assert response.status_code == 200, response.text
        (item,) = response.json()["items"]
        assert item["id"] == str(identity) and item["status"] == "NEW"
        assert item["phone_number"] == "+573000000001"
    detail = await client.get(root + f"/prospects/{identity}")
    assert detail.status_code == 200, detail.text
    (event,) = detail.json()["events"]["items"]
    assert event["agent_instance_id"] == str(world[3])
    assert event["agent_version_id"] == str(world[4])
    assert event["conversation_id"] == str(world[2])
    assert (
        event["evidence"][0]["quote"] == "Soy Ana de Nexo. Quiero un agente de ventas"
    )
    linked = await client.get(root + f"/conversations/{world[2]}/prospect")
    assert linked.status_code == 200 and linked.json()["id"] == str(identity)


async def test_foreign_missing_filter_and_cursor_cannot_cross_scope(
    configuration_client, session_factory
):
    client, _ = configuration_client
    first, identity = await prospect(session_factory)
    second, foreign = await prospect(session_factory)
    root = f"/admin/agent-workspace/companies/{first[0].tenant_id}"
    for target in (foreign, uuid4()):
        response = await client.get(root + f"/prospects/{target}")
        assert response.status_code == 404
    response = await client.get(
        root + "/prospects", params={"agent_id": str(second[3])}
    )
    assert response.status_code == 404
    assert (
        await client.get(root + "/prospects", params={"limit": 21})
    ).status_code == 422
    assert (
        await client.get(root + "/prospects", params={"q": "x" * 201})
    ).status_code == 422
    empty = await client.get(root + "/prospects", params={"q": "%"})
    assert empty.json()["items"] == []


async def test_pagination_scope_and_detail_outside_current_page(
    configuration_client, session_factory
):
    client, _ = configuration_client
    first, identity = await prospect(session_factory)
    second = await seed(
        session_factory, tenant=first[0].tenant_id, phone="573000000002"
    )
    _, other = await prospect(session_factory, second)
    root = f"/admin/agent-workspace/companies/{first[0].tenant_id}"
    page = (await client.get(root + "/prospects", params={"limit": 1})).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    next_page = await client.get(
        root + "/prospects", params={"limit": 1, "cursor": page["next_cursor"]}
    )
    assert {page["items"][0]["id"], next_page.json()["items"][0]["id"]} == {
        str(identity),
        str(other),
    }
    assert (await client.get(root + f"/prospects/{identity}")).status_code == 200
    assert (
        await client.get(
            root + "/prospects", params={"q": "Ana", "cursor": page["next_cursor"]}
        )
    ).status_code == 404
    foreign = await seed(session_factory)
    foreign_root = f"/admin/agent-workspace/companies/{foreign[0].tenant_id}"
    assert (
        await client.get(
            foreign_root + "/prospects", params={"cursor": page["next_cursor"]}
        )
    ).status_code == 404


async def test_multiple_agents_keep_attribution_and_source_pages(
    configuration_client, session_factory
):
    client, _ = configuration_client
    first, identity = await prospect(session_factory)
    second = await seed(session_factory, tenant=first[0].tenant_id)
    _, repeated = await prospect(session_factory, second)
    assert identity == repeated
    root = f"/admin/agent-workspace/companies/{first[0].tenant_id}"
    for agent in (first[3], second[3]):
        response = await client.get(
            root + "/prospects", params={"agent_id": str(agent)}
        )
        assert len(response.json()["items"]) == 1
    events = await client.get(
        root + f"/prospects/{identity}/events", params={"limit": 1}
    )
    assert events.status_code == 200, events.text
    page = events.json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    next_page = (
        await client.get(
            root + f"/prospects/{identity}/events",
            params={"limit": 1, "cursor": page["next_cursor"]},
        )
    ).json()
    assert {
        page["items"][0]["agent_instance_id"],
        next_page["items"][0]["agent_instance_id"],
    } == {str(first[3]), str(second[3])}


async def test_missing_prospect_is_normal_for_unqualified_conversation(
    configuration_client, session_factory
):
    client, _ = configuration_client
    world = await seed(session_factory)
    path = f"/admin/agent-workspace/companies/{world[0].tenant_id}/conversations/{world[2]}/prospect"
    response = await client.get(path)
    assert response.status_code == 200 and response.json() is None


async def test_prospect_endpoints_require_real_admin_auth(
    configuration_client, session_factory
):
    client, app = configuration_client
    world, _ = await prospect(session_factory)
    path = f"/admin/agent-workspace/companies/{world[0].tenant_id}/prospects"
    app.dependency_overrides.pop(require_platform_admin)
    assert (await client.get(path)).status_code == 401
    assert (
        await client.get(path, headers={"Authorization": "Bearer test-non-admin"})
    ).status_code == 403


async def test_read_exposes_identity_conflict_and_privacy_suppression(
    configuration_client, session_factory
):
    client, _ = configuration_client
    first = await seed(session_factory, opaque="CO.first")
    _, first_id = await prospect(session_factory, first)
    conversation = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES(:id,:tenant,:account,'CO.second')"
            ),
            {"id": conversation, "tenant": first[0].tenant_id, "account": first[1]},
        )
    second = (first[0], first[1], conversation, first[3], first[4], None, "CO.second")
    _, second_id = await prospect(session_factory, second)
    linked = (*first[:5], "573000000001", "CO.second")
    await capture(
        session_factory,
        linked,
        await inbound(
            session_factory, linked, "No guardes mis datos como prospecto", 2
        ),
        operation="SUPPRESS",
    )
    root = f"/admin/agent-workspace/companies/{first[0].tenant_id}"
    for identity in (first_id, second_id):
        response = await client.get(root + f"/prospects/{identity}")
        assert response.status_code == 200, response.text
        assert response.json()["prospect"]["identity_conflict"]
        assert response.json()["prospect"]["capture_suppressed"]
        assert any(
            event["operation"] == "CONFLICT"
            for event in response.json()["events"]["items"]
        )
