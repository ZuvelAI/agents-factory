import asyncio
import hashlib
import hmac
import json
from uuid import uuid4
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from agents_factory.common.context import TenantContext
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.conversations.models import AwaitingHumanPolicy

from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.webhook import MetaWebhookProcessor


async def _seed_mobile_account(session_factory, label):
    tenant, account = uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES (:id, :slug, 'Mobile safety')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id, tenant_id, provider, waba_id, phone_number_id, status, mode, coexistence_eligibility) VALUES (:id, :tenant, 'meta', :waba, :phone, 'active', 'COEXISTENCE', 'ELIGIBLE')"
            ),
            {
                "id": account,
                "tenant": tenant,
                "waba": f"waba-{label}",
                "phone": f"phone-{label}",
            },
        )
    return tenant, account


def _mobile_body(label, recipients, prefix):
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": f"waba-{label}",
                    "changes": [
                        {
                            "field": "smb_message_echoes",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": f"phone-{label}"},
                                "message_echoes": [
                                    {
                                        "id": f"wamid.{prefix}.{recipient}",
                                        "from": "573000000099",
                                        "to": recipient,
                                        "timestamp": "1700255121",
                                        "type": "text",
                                        "text": {"body": "Atención humana"},
                                    }
                                    for recipient in recipients
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()


async def _process_mobile(session_factory, body):
    signature = "sha256=" + hmac.new(b"test-only", body, hashlib.sha256).hexdigest()
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await session.execute(text("SET LOCAL lock_timeout='700ms'"))
        return await MetaWebhookProcessor(
            session=session,
            provider=MetaCloudApiProvider(app_secret=SecretStr("test-only")),
        ).process(raw_body=body, signature=signature, correlation_id=uuid4())


async def test_reversed_mobile_batches_do_not_deadlock(session_factory, monkeypatch):
    from agents_factory.modules.whatsapp import webhook

    tenant, _ = await _seed_mobile_account(session_factory, "batch")
    original = webhook.ingest_mobile_echo

    async def yield_after_persist(*args, **kwargs):
        result = await original(*args, **kwargs)
        await asyncio.sleep(
            0.1
        )  # Force overlapping real transactions; keep all writes/locks.
        return result

    monkeypatch.setattr(webhook, "ingest_mobile_echo", yield_after_persist)
    results = await asyncio.gather(
        _process_mobile(
            session_factory,
            _mobile_body("batch", ["573000000001", "573000000002"], "first"),
        ),
        _process_mobile(
            session_factory,
            _mobile_body("batch", ["573000000002", "573000000001"], "second"),
        ),
        return_exceptions=True,
    )
    assert not any(isinstance(result, BaseException) for result in results), results
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
            == 4
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.conversations WHERE tenant_id=:tenant AND control_state='HUMAN_ACTIVE'"
                ),
                {"tenant": tenant},
            )
            == 2
        )


@pytest.mark.parametrize("wrong_field", ["waba_id", "phone_number_id"])
async def test_mobile_echo_rejects_mismatched_asset_identity(
    session_factory, wrong_field
):
    from agents_factory.common.errors import DomainError
    from agents_factory.modules.whatsapp.contracts import WhatsAppMobileEcho
    from agents_factory.modules.whatsapp.mobile_echo import ingest_mobile_echo
    from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping

    tenant, account = await _seed_mobile_account(session_factory, "identity")
    event = {
        "waba_id": "waba-identity",
        "phone_number_id": "phone-identity",
        "whatsapp_message_id": "wamid.identity",
        "recipient_wa_id": "573000000001",
        "message_type": "text",
        "content": {"text": "Hello"},
        "occurred_at": datetime.now(UTC),
    }
    event[wrong_field] = "other-account"
    with pytest.raises(DomainError):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await ingest_mobile_echo(
                session,
                context=TenantContext(
                    tenant_id=tenant,
                    actor_id=None,
                    actor_type="system",
                    correlation_id=uuid4(),
                ),
                mapping=WhatsAppAccountMapping(account_id=account, tenant_id=tenant),
                event=WhatsAppMobileEcho(**event),
            )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
            == 0
        )


async def test_same_mobile_message_identity_stays_isolated_between_tenants(
    session_factory,
):
    first, _ = await _seed_mobile_account(session_factory, "first-tenant")
    second, _ = await _seed_mobile_account(session_factory, "second-tenant")
    for label in ("first-tenant", "second-tenant"):
        result = await _process_mobile(
            session_factory, _mobile_body(label, ["573000000001"], "same-id")
        )
        assert result.accepted_messages == 1
    async with session_factory.begin() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT tenant_id, count(*) AS count FROM public.messages GROUP BY tenant_id"
                    )
                )
            )
            .mappings()
            .all()
        )
        assert {row["tenant_id"]: row["count"] for row in rows} == {first: 1, second: 1}
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        from agents_factory.database import set_tenant_context

        await set_tenant_context(session, first)
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE tenant_id=:tenant"),
                {"tenant": second},
            )
            == 0
        )


@pytest.mark.parametrize("condition", ["API_ONLY", "inactive", "wrong_tenant"])
async def test_mobile_takeover_rejects_invalid_account_scope(
    session_factory, condition
):
    from agents_factory.common.errors import DomainError
    from agents_factory.modules.whatsapp.contracts import WhatsAppMobileEcho
    from agents_factory.modules.whatsapp.mobile_echo import ingest_mobile_echo
    from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping

    tenant, account = await _seed_mobile_account(session_factory, "scope")
    other, _ = await _seed_mobile_account(session_factory, "other-scope")
    async with session_factory.begin() as session:
        if condition == "API_ONLY":
            await session.execute(
                text(
                    "UPDATE public.whatsapp_accounts SET mode='API_ONLY' WHERE id=:id"
                ),
                {"id": account},
            )
        elif condition == "inactive":
            await session.execute(
                text(
                    "UPDATE public.whatsapp_accounts SET status='inactive' WHERE id=:id"
                ),
                {"id": account},
            )
    with pytest.raises(DomainError):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await ingest_mobile_echo(
                session,
                context=TenantContext(
                    tenant_id=other if condition == "wrong_tenant" else tenant,
                    actor_id=None,
                    actor_type="system",
                    correlation_id=uuid4(),
                ),
                mapping=WhatsAppAccountMapping(account_id=account, tenant_id=tenant),
                event=WhatsAppMobileEcho(
                    waba_id="waba-scope",
                    phone_number_id="phone-scope",
                    whatsapp_message_id="wamid.scope",
                    recipient_wa_id="573000000001",
                    message_type="text",
                    content={"text": "Hello"},
                    occurred_at=datetime.now(UTC),
                ),
            )
    async with session_factory.begin() as session:
        assert await session.scalar(text("SELECT count(*) FROM public.messages")) == 0
        assert (
            await session.scalar(text("SELECT count(*) FROM public.conversations")) == 0
        )


async def test_invalid_mobile_signature_cannot_take_control(session_factory):
    from agents_factory.modules.whatsapp.webhook import InvalidWebhookSignature

    await _seed_mobile_account(session_factory, "signature")
    with pytest.raises(InvalidWebhookSignature):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await MetaWebhookProcessor(
                session=session,
                provider=MetaCloudApiProvider(app_secret=SecretStr("test-only")),
            ).process(
                raw_body=_mobile_body("signature", ["573000000001"], "invalid"),
                signature="sha256=" + "0" * 64,
                correlation_id=uuid4(),
            )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.conversations")) == 0
        )


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
