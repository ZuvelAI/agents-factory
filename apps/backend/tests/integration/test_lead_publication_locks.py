"""Real publication paths must wait before locking a runtime-owned account."""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import text

from agents_factory.common.account_lifecycle import lock_account_lifecycle
from agents_factory.modules.leads.service import LeadCaptureService
from agents_factory.modules.leads.models import LeadProposal
from agents_factory.modules.agent_factory.workspace_publication_service import (
    WorkspacePublicationService,
)
from agents_factory.modules.agent_factory.publication_service import (
    PanelPublicationService,
)
from apps.backend.tests.integration.test_agent_configuration import (
    configuration_client as _client,
)
from apps.backend.tests.integration.test_workspace_publication_candidates import (
    ready_agent,
)
from apps.backend.tests.integration.test_workspace_agent_publication import (
    reviewed_candidate,
)
from apps.backend.tests.integration.agent_factory.test_channel_publication import (
    prepare_reviewed,
)
from apps.backend.tests.integration.agent_factory.test_publication_candidates import (
    configuration,
    context,
)
from apps.backend.tests.integration.test_lead_capture import seed, inbound, TEXT

configuration_client = _client


@pytest.mark.parametrize("surface", ["workspace", "legacy"])
async def test_full_publication_waits_before_account_row_and_allows_first_capture(
    configuration_client, session_factory, surface
):
    client, _ = configuration_client
    _, draft = await ready_agent(client)
    tenant = UUID(draft["tenant_id"])
    world = await seed(session_factory, tenant=tenant)
    message, history = await inbound(session_factory, world, operational_admission=False)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET health_status='HEALTHY' WHERE id=:account"
            ),
            {"account": world[1]},
        )
    if surface == "workspace":
        candidate, proof = await reviewed_candidate(session_factory, draft)
    else:
        from sqlalchemy import bindparam
        from sqlalchemy.dialects.postgresql import JSONB

        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO public.tenant_onboarding_configs(tenant_id,revision,configuration) VALUES(:tenant,1,:config)"
                ).bindparams(bindparam("config", type_=JSONB)),
                {"tenant": tenant, "config": configuration().model_dump(mode="json")},
            )
        candidate, proof = await prepare_reviewed(
            session_factory, tenant, context(tenant)
        )
    started = asyncio.Event()
    publisher_pid = None

    async def publish():
        nonlocal publisher_pid
        async with session_factory.begin() as session:
            publisher_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            started.set()
            if surface == "workspace":
                return await WorkspacePublicationService(
                    session, context(tenant), code_digest="a" * 64
                ).publish(
                    agent_id=UUID(draft["agent_instance_id"]),
                    expected_revision=draft["revision"],
                    version_id=candidate.version.id,
                    test_run_id=proof.id,
                    whatsapp_account_id=world[1],
                    expected_binding_revision=0,
                    expected_current_agent_id=None,
                    confirm_publish=True,
                )
            return await PanelPublicationService(
                session, context(tenant), code_digest="a" * 64
            ).publish(
                version_id=candidate.id,
                whatsapp_account_id=world[1],
                expected_revision=1,
                test_run_id=proof.id,
                expected_binding_revision=0,
            )

    writer = None
    try:
        async with session_factory.begin() as runtime:
            await runtime.execute(text("SET LOCAL ROLE agents_factory_app"))
            await lock_account_lifecycle(runtime, tenant, world[1])
            writer = asyncio.create_task(publish())
            await asyncio.wait_for(started.wait(), 2)
            async with asyncio.timeout(3):
                async with session_factory() as observer:
                    while not await observer.scalar(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=:pid AND wait_event='advisory')"
                        ),
                        {"pid": publisher_pid},
                    ):
                        if writer.done():
                            await writer
                        await asyncio.sleep(0.01)
            service = LeadCaptureService(runtime, world[0])
            trusted = await service.context_for(
                conversation_id=world[2],
                inbound_message_id=message,
                agent_instance_id=world[3],
                agent_version_id=world[4],
            )
            assert trusted is not None
            # The first PROVIDER key needs a FK lock on the same account.
            async with asyncio.timeout(0.5):
                result = await service.apply(
                    LeadProposal(
                        operation="CAPTURE",
                        evidence=[{"message_id": message, "quote": TEXT}],
                    ),
                    trusted,
                    history,
                )
            assert result.status == "RECORDED"
    finally:
        if writer is not None:
            await asyncio.wait_for(writer, 3)
