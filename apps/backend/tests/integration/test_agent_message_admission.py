from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_operations.service import AgentOperationService
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


async def build_operation_world(session_factory):
    tenant = await seed(session_factory, configuration())
    admin = context(tenant)
    channel = await account(session_factory, tenant)
    candidate, run = await prepare_reviewed(session_factory, tenant, admin)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await PanelPublicationService(session, admin, code_digest="a" * 64).publish(
            version_id=candidate.id,
            whatsapp_account_id=channel,
            expected_revision=1,
            test_run_id=run.id,
            expected_binding_revision=0,
        )
    return admin, channel, candidate.agent_instance_id


@pytest_asyncio.fixture
async def operation_world(session_factory):
    return await build_operation_world(session_factory)


async def change_state(factory, world, enabled, revision):
    admin, _, agent = world
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return await AgentOperationService(session, admin).transition(
            agent_id=agent,
            enabled=enabled,
            expected_revision=revision,
        )


async def admit_fixture(factory, world, *, occurred_at, event_id=None):
    from agents_factory.modules.agent_operations.admission import admit_event

    admin, channel, _ = world
    event_id = event_id or uuid4()
    async with factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_webhook_events "
                "(id,tenant_id,whatsapp_account_id,whatsapp_message_id,sender_wa_id,message_type,normalized_content,provider_timestamp,raw_payload) "
                "VALUES(:event,:tenant,:account,:provider,'573101234567','text','{\"text\":\"Hola\"}',:at,'{}') ON CONFLICT DO NOTHING"
            ),
            {
                "event": event_id,
                "tenant": admin.tenant_id,
                "account": channel,
                "provider": f"wamid.{event_id}",
                "at": occurred_at or datetime.now(UTC),
            },
        )
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        return await admit_event(
            session,
            admin,
            event_id=event_id,
            account_id=channel,
            provider_timestamp=occurred_at,
        )


@pytest.mark.asyncio
async def test_paused_admission_is_not_revived_by_replay(
    session_factory, operation_world
):
    world = operation_world
    await change_state(session_factory, world, False, 1)
    event = uuid4()
    at = datetime.now(UTC)
    first = await admit_fixture(session_factory, world, occurred_at=at, event_id=event)
    assert first.eligible is False and first.reason == "paused"
    await change_state(session_factory, world, True, 2)
    replay = await admit_fixture(session_factory, world, occurred_at=at, event_id=event)
    assert replay == first
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_webhook_events")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_resume_cut_rejects_old_equal_and_missing_timestamps(
    session_factory, operation_world
):
    world = operation_world
    await change_state(session_factory, world, False, 1)
    resumed = await change_state(session_factory, world, True, 2)
    for at, reason in [
        (resumed.resumed_at - timedelta(seconds=1), "before_resume"),
        (resumed.resumed_at, "before_resume"),
        (None, "invalid_timestamp"),
    ]:
        admission = await admit_fixture(session_factory, world, occurred_at=at)
        assert admission.eligible is False and admission.reason == reason
    new = await admit_fixture(
        session_factory, world, occurred_at=resumed.resumed_at + timedelta(seconds=1)
    )
    assert new.eligible is True and new.operation_revision == 3


@pytest.mark.asyncio
async def test_admission_uses_receipt_state_not_later_ingestion(
    session_factory, operation_world
):
    from agents_factory.modules.agent_operations.admission import (
        check_message_eligibility,
    )
    from agents_factory.modules.conversations.service import ConversationService
    from agents_factory.modules.conversations.models import AwaitingHumanPolicy

    world = operation_world
    admission = await admit_fixture(
        session_factory, world, occurred_at=datetime.now(UTC)
    )
    assert admission.eligible is True
    await change_state(session_factory, world, False, 1)
    await change_state(session_factory, world, True, 2)
    admin, _, _ = world
    operation = TenantContext(admin.tenant_id, None, "system", uuid4())
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, admin.tenant_id)
        result = await ConversationService(
            session=session,
            context=operation,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(admission.source_event_id)
        assert (
            await check_message_eligibility(
                session, operation, message_id=result.message_id
            )
            is False
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE direction='inbound'")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_missing_admission_never_authorizes_history_or_old_work(
    session_factory, operation_world
):
    from agents_factory.modules.agent_operations.admission import (
        check_message_eligibility,
    )

    admin, _, _ = operation_world
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        assert (
            await check_message_eligibility(session, admin, message_id=uuid4()) is False
        )


@pytest.mark.asyncio
async def test_new_message_retains_positive_authority(session_factory, operation_world):
    from agents_factory.modules.agent_operations.admission import (
        check_message_eligibility,
    )
    from agents_factory.modules.conversations.service import ConversationService
    from agents_factory.modules.conversations.models import AwaitingHumanPolicy

    admin, _, _ = operation_world
    admitted = await admit_fixture(
        session_factory, operation_world, occurred_at=datetime.now(UTC)
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        result = await ConversationService(
            session=session,
            context=admin,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(admitted.source_event_id)
        assert (
            await check_message_eligibility(
                session, admin, message_id=result.message_id
            )
            is True
        )


@pytest.mark.asyncio
async def test_real_webhook_records_authority_before_message_worker(
    session_factory, operation_world
):
    import json
    from pydantic import SecretStr
    from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
    from agents_factory.modules.whatsapp.webhook import MetaWebhookProcessor
    from apps.backend.tests.integration.test_whatsapp_deduplication import (
        FIXTURE,
        APP_SECRET,
        _signature,
    )

    admin, channel, agent = operation_world
    await change_state(session_factory, operation_world, False, 1)
    async with session_factory.begin() as session:
        account_row = (
            (
                await session.execute(
                    text(
                        "SELECT waba_id,phone_number_id FROM public.whatsapp_accounts WHERE id=:a"
                    ),
                    {"a": channel},
                )
            )
            .mappings()
            .one()
        )
    payload = json.loads(FIXTURE.read_bytes())
    payload["entry"][0]["id"] = account_row["waba_id"]
    payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = (
        account_row["phone_number_id"]
    )
    body = json.dumps(payload).encode()
    for _ in range(2):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await MetaWebhookProcessor(
                session=session,
                provider=MetaCloudApiProvider(app_secret=SecretStr(APP_SECRET)),
            ).process(raw_body=body, signature=_signature(body), correlation_id=uuid4())
    async with session_factory.begin() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT agent_instance_id,eligible,reason FROM public.agent_message_admissions"
                    )
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 1
        assert dict(rows[0]) == {
            "agent_instance_id": agent,
            "eligible": False,
            "reason": "paused",
        }
        assert await session.scalar(text("SELECT count(*) FROM public.messages")) == 0


@pytest.mark.asyncio
async def test_admission_waits_for_concurrent_binding_commit(
    session_factory, operation_world
):
    import asyncio
    from agents_factory.common.account_lifecycle import lock_account_lifecycle
    from agents_factory.modules.agent_factory.channel_binding import (
        AccountAgentBindingRepository,
    )
    from agents_factory.modules.agent_factory.repository import AgentSpecRepository

    admin, channel, _ = operation_world
    task = None
    try:
        async with session_factory.begin() as first:
            await first.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(first, admin.tenant_id)
            await lock_account_lifecycle(first, admin.tenant_id, channel)
            binding_repo = AccountAgentBindingRepository(first, admin)
            binding = await binding_repo.get_for_account(channel)
            version = await AgentSpecRepository(first, admin).get_version(
                binding.version_id
            )
            task = asyncio.create_task(
                admit_fixture(
                    session_factory, operation_world, occurred_at=datetime.now(UTC)
                )
            )

            async def wait_until_blocked():
                while True:
                    async with session_factory.begin() as probe:
                        if await probe.scalar(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted)"
                            )
                        ):
                            return
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_until_blocked(), 3)
            await binding_repo.bind(
                channel, version, expected_revision=1, action="PUBLISH"
            )
        admitted = await asyncio.wait_for(task, 3)
        assert admitted.binding_revision == 2
        assert admitted.eligible is True
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
