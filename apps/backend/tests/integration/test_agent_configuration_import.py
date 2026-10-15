"""Legacy import must target one verified instance and never overwrite edits."""

from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from apps.backend.tests.integration.test_agent_configuration import configuration_client  # noqa: F401


async def legacy_fixture(session_factory):
    tenant, first, second, version = [uuid4() for _ in range(4)]
    config = {
        "company": {"commercial_name": "Zuvel"},
        "agent": {
            "agent_name": "Asistente original",
            "model": "gpt-6-luna",
            "instructions": "Instrucción heredada",
        },
    }
    async with session_factory.begin() as session:
        await session.execute(
            text("INSERT INTO public.tenants(id,slug,name) VALUES(:id,:slug,'Zuvel')"),
            {"id": tenant, "slug": str(tenant)},
        )
        for agent in (first, second):
            await session.execute(
                text(
                    "INSERT INTO public.agent_instances(id,tenant_id,product) VALUES(:id,:tenant,'Agent Customer Service')"
                ),
                {"id": agent, "tenant": tenant},
            )
        await session.execute(
            text(
                "INSERT INTO public.tenant_onboarding_configs(tenant_id,revision,configuration) VALUES(:tenant,4,:config)"
            ).bindparams(bindparam("config", type_=JSONB)),
            {"tenant": tenant, "config": config},
        )
        await session.execute(
            text(
                "INSERT INTO public.agent_spec_versions(id,tenant_id,agent_instance_id,version_number,state,configuration) VALUES(:id,:tenant,:agent,1,'DRAFT','{}')"
            ),
            {"id": version, "tenant": tenant, "agent": first},
        )
        await session.execute(
            text(
                "INSERT INTO public.panel_agent_candidates(tenant_id,onboarding_revision,code_digest,version_id) VALUES(:tenant,4,:digest,:version)"
            ),
            {"tenant": tenant, "digest": "a" * 64, "version": version},
        )
    return tenant, first, second


@pytest.mark.asyncio
async def test_import_targets_only_selected_instance_and_is_idempotent(
    configuration_client, session_factory
):
    client, _ = configuration_client
    tenant, first, second = await legacy_fixture(session_factory)
    base = f"/admin/agent-workspace/companies/{tenant}/agents"
    request = {"expected_legacy_revision": 4, "expected_company_revision": 0}
    assert (
        await client.post(f"{base}/{second}/configuration/import-legacy", json=request)
    ).status_code == 409
    path = f"{base}/{first}/configuration/import-legacy"
    first_response = await client.post(path, json=request)
    assert first_response.status_code == 200, first_response.text
    draft = first_response.json()
    assert draft["configuration"]["agent"]["agent_name"] == "Asistente original"
    assert draft["configuration"]["purpose"] == ""
    assert draft["provenance"]["legacy_revision"] == 4
    retry = await client.post(path, json={**request, "expected_company_revision": 1})
    assert retry.status_code == 200 and retry.json()["revision"] == 1
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.agent_configuration_drafts")
            )
            == 1
        )
        assert (
            await session.scalar(
                text(
                    "SELECT revision FROM public.tenant_onboarding_configs WHERE tenant_id=:tenant"
                ),
                {"tenant": tenant},
            )
            == 4
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.panel_agent_candidates")
            )
            == 1
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE event_type='agent.legacy_configuration_imported'"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_import_rejects_stale_source_and_never_overwrites_edited_draft(
    configuration_client, session_factory
):
    client, _ = configuration_client
    tenant, first, _ = await legacy_fixture(session_factory)
    path = f"/admin/agent-workspace/companies/{tenant}/agents/{first}/configuration"
    assert (
        await client.post(
            path + "/import-legacy",
            json={"expected_legacy_revision": 3, "expected_company_revision": 0},
        )
    ).status_code == 409
    draft = (
        await client.post(
            path + "/import-legacy",
            json={"expected_legacy_revision": 4, "expected_company_revision": 0},
        )
    ).json()
    draft["configuration"]["purpose"] = "Editado después"
    assert (
        await client.put(
            path, json={"expected_revision": 1, "configuration": draft["configuration"]}
        )
    ).status_code == 200
    assert (
        await client.post(
            path + "/import-legacy",
            json={"expected_legacy_revision": 4, "expected_company_revision": 1},
        )
    ).status_code == 409
    assert (await client.get(path)).json()["configuration"][
        "purpose"
    ] == "Editado después"
