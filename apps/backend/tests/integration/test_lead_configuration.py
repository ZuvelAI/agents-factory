"""Saving a lead flag changes only that agent's draft, never its channel."""

from sqlalchemy import text

from test_agent_configuration import configuration_client as _configuration_client, create_company_and_agent

configuration_client = _configuration_client


async def test_lead_flag_is_agent_scoped_and_save_never_publishes(
    configuration_client, session_factory
):
    client, _ = configuration_client
    root, first = await create_company_and_agent(client)
    second = (await client.post(root + "/agents", json={"name": "Soporte"})).json()
    path = root + f"/agents/{first['agent_instance_id']}/configuration"
    changed = first["configuration"]
    changed["lead_capture"] = {"enabled": True}
    result = await client.put(
        path, json={"expected_revision": 1, "configuration": changed}
    )
    assert result.status_code == 200, result.text
    assert result.json()["configuration"]["lead_capture"] == {"enabled": True}
    other = await client.get(
        root + f"/agents/{second['agent_instance_id']}/configuration"
    )
    assert (
        not other.json()["configuration"].get("lead_capture", {}).get("enabled", False)
    )
    again = await client.put(
        path,
        json={"expected_revision": 2, "configuration": result.json()["configuration"]},
    )
    assert again.status_code == 200, again.text
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

    changed["lead_capture"] = {"enabled": False}
    off = await client.put(
        path, json={"expected_revision": 3, "configuration": changed}
    )
    assert off.status_code == 200, off.text
    async with session_factory.begin() as session:
        sections = await session.scalar(
            text(
                "SELECT payload->'sections' FROM public.audit_events WHERE event_type='agent.configuration_saved' AND payload->>'revision'='4'"
            )
        )
        assert "lead_capture" in sections


async def test_legacy_connector_edit_still_denied_with_lead_flag(configuration_client):
    client, _ = configuration_client
    root, draft = await create_company_and_agent(client)
    config = draft["configuration"]
    config["lead_capture"] = {"enabled": True}
    config["integrations"]["required_connectors"] = ["invented_crm"]
    response = await client.put(
        root + f"/agents/{draft['agent_instance_id']}/configuration",
        json={"expected_revision": 1, "configuration": config},
    )
    assert response.status_code == 422
