import asyncio
import json
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from agents_factory.common.account_lifecycle import account_lifecycle_key
from agents_factory.modules.agent_operations.repository import AgentOperationRepository
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.webhook import MetaWebhookProcessor
from apps.backend.tests.integration.agent_factory.test_channel_publication import (
    account,
)
from apps.backend.tests.integration.test_agent_message_admission import (
    operation_world as _operation_world,
)
from apps.backend.tests.integration.test_whatsapp_deduplication import (
    FIXTURE,
    APP_SECRET,
    _signature,
)

operation_world = _operation_world


@pytest.mark.asyncio
async def test_mixed_inbound_disconnect_fences_all_accounts_before_agent(
    session_factory,
    operation_world,
    monkeypatch,
):
    admin, inbound_account, _ = operation_world
    removed_account = await account(session_factory, admin.tenant_id)
    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT waba_id,phone_number_id FROM public.whatsapp_accounts WHERE id=:a"
                    ),
                    {"a": inbound_account},
                )
            )
            .mappings()
            .one()
        )
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET waba_id=:w, mode='COEXISTENCE', coexistence_eligibility='ELIGIBLE', display_phone_digits='573000000001', verified_at='2020-01-01Z' WHERE id=:a"
            ),
            {"w": row["waba_id"], "a": removed_account},
        )
        await session.execute(
            text(
                "INSERT INTO public.account_agent_bindings(tenant_id,whatsapp_account_id,agent_instance_id,version_id,revision) SELECT tenant_id,:b,agent_instance_id,version_id,revision FROM public.account_agent_bindings WHERE whatsapp_account_id=:a"
            ),
            {"a": inbound_account, "b": removed_account},
        )
    payload = json.loads(FIXTURE.read_bytes())
    entry = payload["entry"][0]
    entry["id"] = row["waba_id"]
    entry["changes"][0]["value"]["metadata"]["phone_number_id"] = row["phone_number_id"]
    entry["time"] = 1792530000
    entry["changes"].append(
        {
            "field": "account_update",
            "value": {"event": "PARTNER_REMOVED", "phone_number": "+573000000001"},
        }
    )
    checked = []
    original = AgentOperationRepository.lock

    async def competing_dispatch():
        async with session_factory.begin() as other:
            return await other.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": account_lifecycle_key(admin.tenant_id, removed_account)},
            )

    async def inspect_order(repository, agent_id):
        # A genuinely separate transaction must already be excluded from B
        # when webhook A is about to acquire their shared agent fence.
        checked.append(await asyncio.create_task(competing_dispatch()))
        await original(repository, agent_id)

    monkeypatch.setattr(AgentOperationRepository, "lock", inspect_order)
    body = json.dumps(payload).encode()
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        result = await MetaWebhookProcessor(
            session=session,
            provider=MetaCloudApiProvider(app_secret=SecretStr(APP_SECRET)),
        ).process(raw_body=body, signature=_signature(body), correlation_id=uuid4())
    assert checked and not any(checked)
    assert result.accepted_messages == 1
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT status FROM public.whatsapp_accounts WHERE id=:a"),
                {"a": removed_account},
            )
            == "inactive"
        )
