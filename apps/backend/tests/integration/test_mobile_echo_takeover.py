import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from agents_factory.common.context import TenantContext
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.conversations.models import AwaitingHumanPolicy

from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.webhook import MetaWebhookProcessor


@pytest.mark.parametrize(
    "initial_state", [None, "AI_ACTIVE", "AWAITING_HUMAN", "HUMAN_ACTIVE", "CLOSED"]
)
async def test_signed_mobile_reply_takes_control_without_queuing_ai(
    session_factory, initial_state
):
    tenant_id, account_id, conversation_id = uuid4(), uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES (:id, :slug, 'Echo test')"
            ),
            {"id": tenant_id, "slug": str(tenant_id)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id, tenant_id, provider, waba_id, phone_number_id, status, mode, coexistence_eligibility) VALUES (:id, :tenant, 'meta', 'waba-echo', 'phone-echo', 'active', 'COEXISTENCE', 'ELIGIBLE')"
            ),
            {"id": account_id, "tenant": tenant_id},
        )
        if initial_state:
            await session.execute(
                text(
                    "INSERT INTO public.conversations (id, tenant_id, whatsapp_account_id, customer_wa_id) VALUES (:id, :tenant, :account, '573000000001')"
                ),
                {"id": conversation_id, "tenant": tenant_id, "account": account_id},
            )
            conversations = ConversationService(
                session=session,
                context=TenantContext(
                    tenant_id=tenant_id,
                    actor_type="system",
                    actor_id=None,
                    correlation_id=uuid4(),
                ),
                awaiting_human_policy=AwaitingHumanPolicy.SILENT,
            )
            if initial_state in {"AWAITING_HUMAN", "HUMAN_ACTIVE"}:
                await conversations.request_handoff(
                    conversation_id=conversation_id, reason="test_setup"
                )
            if initial_state == "HUMAN_ACTIVE":
                await conversations.activate_human(
                    conversation_id=conversation_id, reason="test_setup"
                )
            if initial_state == "CLOSED":
                await conversations.close_conversation(
                    conversation_id=conversation_id, reason="test_setup"
                )

    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "waba-echo",
                    "changes": [
                        {
                            "field": "smb_message_echoes",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": "phone-echo"},
                                "message_echoes": [
                                    {
                                        "id": "wamid.mobile",
                                        "from": "573000000099",
                                        "to": "573000000001",
                                        "timestamp": "1700255121",
                                        "type": "text",
                                        "text": {"body": "Yo te atiendo"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
    signature = "sha256=" + hmac.new(b"test-only", body, hashlib.sha256).hexdigest()
    for attempt in range(2):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            result = await MetaWebhookProcessor(
                session=session,
                provider=MetaCloudApiProvider(app_secret=SecretStr("test-only")),
            ).process(raw_body=body, signature=signature, correlation_id=uuid4())
            assert result.accepted_messages == (1 if attempt == 0 else 0)
            assert result.duplicate_messages == (0 if attempt == 0 else 1)

    async with session_factory.begin() as session:
        conversation = (
            await session.execute(
                text(
                    "SELECT control_state FROM public.conversations WHERE tenant_id=:tenant"
                ),
                {"tenant": tenant_id},
            )
        ).scalar_one()
        assert conversation == "HUMAN_ACTIVE"
        messages = (
            (
                await session.execute(
                    text(
                        "SELECT direction, sender_type, content FROM public.messages WHERE tenant_id=:tenant"
                    ),
                    {"tenant": tenant_id},
                )
            )
            .mappings()
            .all()
        )
        assert len(messages) == 1
        assert messages[0]["direction"] == "outbound"
        assert messages[0]["sender_type"] == "human"
        assert messages[0]["content"] == {"text": "Yo te atiendo"}
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.outbox_jobs WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )
            == 0
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE tenant_id=:tenant AND event_type='conversation.mobile_reply.received'"
                ),
                {"tenant": tenant_id},
            )
            == 1
        )
