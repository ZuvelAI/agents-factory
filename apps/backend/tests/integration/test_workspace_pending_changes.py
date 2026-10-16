"""The operator's pending badge follows exact published draft provenance."""

from uuid import UUID

import pytest
from sqlalchemy import text

from apps.backend.tests.integration.test_agent_configuration import (
    configuration_client as _client,
)
from apps.backend.tests.integration.test_workspace_publication_candidates import (
    ready_agent,
)
from apps.backend.tests.integration.test_workspace_agent_publication import (
    reviewed_candidate,
    publish,
)
from apps.backend.tests.integration.agent_factory.test_channel_publication import (
    account,
)
from apps.backend.tests.integration.agent_factory.test_publication_candidates import (
    context,
)

configuration_client = _client


async def pending_views(client, root, draft, expected):
    agent = draft["agent_instance_id"]
    overview = await client.get(f"{root}/agents/{agent}")
    listed = await client.get(f"{root}/agents")
    companies = await client.get("/admin/agent-workspace/companies")
    assert overview.status_code == listed.status_code == companies.status_code == 200
    detail = overview.json()
    summaries = [
        detail["summary"],
        next(item for item in listed.json()["items"] if item["id"] == agent),
        next(
            item
            for company in companies.json()["items"]
            for item in company["agents"]
            if item["id"] == agent
        ),
    ]
    assert [summary["has_pending_changes"] for summary in summaries] == [expected] * 3
    return detail


@pytest.mark.asyncio
async def test_published_exact_draft_is_not_pending_until_shared_company_changes(
    configuration_client, session_factory
):
    client, _ = configuration_client
    root, draft = await ready_agent(client)
    await pending_views(client, root, draft, True)
    selected = await account(session_factory, UUID(draft["tenant_id"]))
    candidate, run = await reviewed_candidate(session_factory, draft)
    await pending_views(client, root, draft, True)
    await publish(session_factory, draft, candidate, run, selected)
    detail = await pending_views(client, root, draft, False)
    assert not any(
        "siguiente entrega" in notice.lower()
        for notice in detail["unavailable_sections"]
    )
    profile = (await client.get(root + "/profile")).json()
    changed = dict(
        profile["configuration"], business_description="Nueva descripción compartida"
    )
    response = await client.put(
        root + "/profile",
        json={"expected_revision": profile["revision"], "configuration": changed},
    )
    assert response.status_code == 200
    await pending_views(client, root, draft, True)


@pytest.mark.asyncio
async def test_pending_tracks_edit_and_rollback_without_relabeling_other_account(
    configuration_client, session_factory
):
    from agents_factory.modules.agent_factory.workspace_publication_service import (
        WorkspacePublicationService,
    )

    client, _ = configuration_client
    root, draft = await ready_agent(client)
    tenant, agent = UUID(draft["tenant_id"]), UUID(draft["agent_instance_id"])
    first_account = await account(session_factory, tenant)
    other_account = await account(session_factory, tenant)
    first, first_run = await reviewed_candidate(session_factory, draft)
    await publish(session_factory, draft, first, first_run, first_account)
    await publish(session_factory, draft, first, first_run, other_account)
    await pending_views(client, root, draft, False)
    config = draft["configuration"]
    config["agent"]["instructions"] = "Nueva configuración pendiente"
    response = await client.put(
        f"{root}/agents/{agent}/configuration",
        json={"expected_revision": draft["revision"], "configuration": config},
    )
    assert response.status_code == 200
    updated = response.json()
    await pending_views(client, root, updated, True)
    second, second_run = await reviewed_candidate(session_factory, updated)
    await publish(session_factory, updated, second, second_run, first_account, 1, agent)
    detail = await pending_views(client, root, updated, False)
    assigned = {
        row["account_id"]: row["version_id"]
        for row in detail["summary"]["channel_accounts"]
    }
    assert assigned == {
        str(first_account): str(second.version.id),
        str(other_account): str(first.version.id),
    }
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await WorkspacePublicationService(
            session, context(tenant), code_digest="a" * 64
        ).rollback(
            agent_id=agent,
            whatsapp_account_id=first_account,
            target_version_id=first.version.id,
            expected_binding_revision=2,
            confirm_rollback=True,
        )
    await pending_views(client, root, updated, True)
