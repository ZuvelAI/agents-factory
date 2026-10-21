"""Operational control is isolated, revisioned and independent of publication."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from apps.backend.tests.integration.test_agent_configuration import (
    configuration_client as _configuration_client,
    create_company_and_agent,
)

configuration_client = _configuration_client


@pytest.mark.asyncio
async def test_controls_are_disabled_until_compatible_workers_are_verified(
    configuration_client,
):
    client, app = configuration_client
    root, draft = await create_company_and_agent(client)
    app.state.agent_operation_controls_enabled = False
    path = root + f"/agents/{draft['agent_instance_id']}/operation"
    assert (await client.get(path)).json()["controls_available"] is False
    response = await client.post(path, json={"enabled": False, "expected_revision": 1})
    assert response.status_code == 503
    assert (await client.get(path)).json()["enabled"] is True


@pytest.mark.asyncio
async def test_workspace_reports_pause_without_changing_connection(
    configuration_client,
):
    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    second = (await client.post(root + "/agents", json={"name": "Soporte"})).json()
    path = root + f"/agents/{draft['agent_instance_id']}/operation"
    await client.post(path, json={"enabled": False, "expected_revision": 1})
    agents = (await client.get(root + "/agents")).json()["items"]
    assert agents[0]["execution_status"] == "paused"
    assert agents[0]["channel_accounts"] == []
    other = (
        await client.get(root + f"/agents/{second['agent_instance_id']}/operation")
    ).json()
    assert other["enabled"] is True and other["revision"] == 1


@pytest.mark.asyncio
async def test_pause_resume_preserves_revisions_and_audits_only_changes(
    configuration_client, session_factory
):
    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    agent_id = draft["agent_instance_id"]
    path = root + f"/agents/{agent_id}/operation"
    initial = await client.get(path)
    assert initial.status_code == 200, initial.text
    assert initial.json()["enabled"] is True
    assert initial.json()["revision"] == 1
    assert initial.json()["resumed_at"] is None
    paused = await client.post(path, json={"enabled": False, "expected_revision": 1})
    assert paused.status_code == 200, paused.text
    assert paused.json()["enabled"] is False
    assert paused.json()["revision"] == 2
    repeated = await client.post(path, json={"enabled": False, "expected_revision": 2})
    assert repeated.json() == paused.json()
    stale_repeat = await client.post(
        path, json={"enabled": False, "expected_revision": 1}
    )
    assert stale_repeat.status_code == 409
    stale = await client.post(path, json={"enabled": True, "expected_revision": 1})
    assert stale.status_code == 409
    resumed = await client.post(path, json={"enabled": True, "expected_revision": 2})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["revision"] == 3
    assert resumed.json()["resumed_at"] is not None
    async with session_factory.begin() as session:
        events = (
            (
                await session.execute(
                    text(
                        "SELECT event_type,payload FROM public.audit_events "
                        "WHERE entity_id=:agent AND entity_type='agent_operation' ORDER BY id"
                    ),
                    {"agent": agent_id},
                )
            )
            .mappings()
            .all()
        )
        assert [r["event_type"] for r in events] == ["agent.paused", "agent.resumed"]
        assert events[0]["payload"] == {
            "enabled": False,
            "previous_revision": 1,
            "revision": 2,
        }
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.agent_spec_versions")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_operation_cannot_target_another_company_agent(configuration_client):
    client, _ = configuration_client
    root, first = await create_company_and_agent(client)
    other_root, other = await create_company_and_agent(client)
    path = root + f"/agents/{other['agent_instance_id']}/operation"
    response = await client.post(path, json={"enabled": False, "expected_revision": 1})
    assert response.status_code == 404
    for base, draft in [(root, first), (other_root, other)]:
        state = await client.get(
            base + f"/agents/{draft['agent_instance_id']}/operation"
        )
        assert state.json()["enabled"] is True
        assert state.json()["revision"] == 1
    missing = await client.get(root + f"/agents/{uuid4()}/operation")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_concurrent_transitions_have_one_winner(configuration_client):
    import asyncio

    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    path = root + f"/agents/{draft['agent_instance_id']}/operation"
    responses = await asyncio.gather(
        *(
            client.post(path, json={"enabled": False, "expected_revision": 1})
            for _ in range(2)
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    current = (await client.get(path)).json()
    assert current["enabled"] is False
    assert current["revision"] == 2


@pytest.mark.asyncio
async def test_non_admin_cannot_change_state(configuration_client, session_factory):
    from uuid import UUID
    from agents_factory.common.context import TenantContext
    from agents_factory.common.errors import DomainError
    from agents_factory.modules.agent_operations.service import AgentOperationService

    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    context = TenantContext(UUID(root.rsplit("/", 1)[1]), uuid4(), "system", uuid4())
    async with session_factory.begin() as session:
        with pytest.raises(DomainError) as error:
            await AgentOperationService(session, context).transition(
                agent_id=UUID(draft["agent_instance_id"]),
                enabled=False,
                expected_revision=1,
            )
        assert error.value.status == 403
    current = await client.get(root + f"/agents/{draft['agent_instance_id']}/operation")
    assert current.json()["revision"] == 1


@pytest.mark.asyncio
async def test_runtime_role_cannot_change_operation_state(
    configuration_client, session_factory
):
    from sqlalchemy.exc import DBAPIError

    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    tenant_id = root.rsplit("/", 1)[1]
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await session.execute(
            text("SELECT set_config('app.tenant_id',:tenant,true)"),
            {"tenant": tenant_id},
        )
        assert (
            await session.scalar(
                text("SELECT enabled FROM public.agent_operation_states")
            )
            is True
        )
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.execute(
                    text("UPDATE public.agent_operation_states SET enabled=false")
                )
        await session.execute(
            text("SELECT set_config('app.tenant_id',:tenant,true)"),
            {"tenant": str(uuid4())},
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.agent_operation_states")
            )
            == 0
        )
