"""Real signed ingestion and scoped reads; no external services or model calls."""

import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from agents_factory.database import set_tenant_context
from agents_factory.common.security import AdminPrincipal
from agents_factory.modules.agent_factory.workspace_conversations import (
    WorkspaceConversationService,
)
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.webhook import MetaWebhookProcessor
from agents_factory.modules.tenants.admin_router import list_admin_conversations
from test_contact_sync import seed


async def deliver(
    session_factory,
    label,
    message_id,
    timestamp,
    profile=None,
    sender="573000000001",
    phone=True,
):
    message = {
        "id": message_id,
        "timestamp": str(timestamp),
        "type": "text",
        "text": {"body": "Hola"},
        "from" if phone else "from_user_id": sender,
    }
    contact = {"wa_id" if phone else "user_id": sender, "profile": profile or {}}
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": f"waba-{label}",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": f"phone-{label}"},
                                "contacts": [contact],
                                "messages": [message],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
    signature = "sha256=" + hmac.new(b"test-only", body, hashlib.sha256).hexdigest()
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        return await MetaWebhookProcessor(
            session=session,
            provider=MetaCloudApiProvider(app_secret=SecretStr("test-only")),
        ).process(raw_body=body, signature=signature, correlation_id=uuid4())


@pytest.mark.asyncio
async def test_signed_ingestion_keeps_identity_without_marking_new_sender_as_phonebook_contact(
    session_factory,
):
    tenant, account = await seed(session_factory, "profile")
    await deliver(
        session_factory,
        "profile",
        "wamid.identity.1",
        1787788800,
        {"name": "Ana", "username": "ana.ventas"},
    )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT to_regclass('public.whatsapp_contact_profiles')")
            )
            is not None
        )
        row = (
            (
                await session.execute(
                    text(
                        "SELECT profile_name, username, phone_number FROM public.whatsapp_contact_profiles"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert dict(row) == {
            "profile_name": "Ana",
            "username": "ana.ventas",
            "phone_number": "+573000000001",
        }
        assert (
            await session.scalar(text("SELECT count(*) FROM public.whatsapp_contacts"))
            == 0
        )
        conversation = uuid4()
        await session.execute(
            text(
                "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES(:id,:tenant,:account,'573000000001')"
            ),
            {"id": conversation, "tenant": tenant, "account": account},
        )
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        reader = WorkspaceConversationService(session)
        result = await reader.get_conversation(
            tenant_id=tenant, conversation_id=conversation
        )
        assert result.contact_name == "Ana"
        assert result.contact_username == "ana.ventas"
        assert result.contact_phone_number == "+573000000001"
        rows = await list_admin_conversations(
            tenant_id=tenant,
            principal=AdminPrincipal(user_id=uuid4(), session_id=uuid4()),
            session=session,
            limit=50,
            offset=0,
        )
        assert rows[0].contact_name == "Ana"
        assert rows[0].contact_phone_number == "+573000000001"


@pytest.mark.asyncio
async def test_missing_stale_and_replayed_metadata_do_not_erase_current_profile(
    session_factory,
):
    await seed(session_factory, "updates")
    await deliver(
        session_factory,
        "updates",
        "wamid.identity.1",
        1787788800,
        {"name": "Ana", "username": "ana.ventas"},
    )
    await deliver(
        session_factory,
        "updates",
        "wamid.identity.2",
        1787788802,
        {"name": "Ana María"},
    )
    await deliver(
        session_factory,
        "updates",
        "wamid.identity.3",
        1787788801,
        {"name": "Nombre viejo", "username": "viejo"},
    )
    replay = await deliver(
        session_factory,
        "updates",
        "wamid.identity.2",
        1787788809,
        {"name": "Replay incorrecto"},
    )
    assert replay.duplicate_messages == 1
    await deliver(session_factory, "updates", "wamid.identity.4", 1787788810)
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT to_regclass('public.whatsapp_contact_profiles')")
            )
            is not None
        )
        row = (
            (
                await session.execute(
                    text(
                        "SELECT profile_name, username, phone_number FROM public.whatsapp_contact_profiles"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert dict(row) == {
            "profile_name": "Ana María",
            "username": "ana.ventas",
            "phone_number": "+573000000001",
        }


@pytest.mark.asyncio
async def test_same_second_message_can_enrich_missing_fields_without_replacing_known_name(
    session_factory,
):
    await seed(session_factory, "same-second")
    await deliver(
        session_factory, "same-second", "wamid.identity.1", 1787788800, {"name": "Ana"}
    )
    await deliver(
        session_factory,
        "same-second",
        "wamid.identity.2",
        1787788800,
        {"name": "Otro nombre", "username": "ana.ventas"},
    )
    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT profile_name,username FROM public.whatsapp_contact_profiles"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert dict(row) == {"profile_name": "Ana", "username": "ana.ventas"}


@pytest.mark.asyncio
async def test_contact_profiles_are_company_and_account_scoped(session_factory):
    first, _ = await seed(session_factory, "identity-first")
    second, _ = await seed(session_factory, "identity-second")
    await deliver(
        session_factory,
        "identity-first",
        "wamid.identity.1",
        1787788800,
        {"name": "Nombre A"},
        "CO.123",
        False,
    )
    await deliver(
        session_factory,
        "identity-second",
        "wamid.identity.2",
        1787788800,
        {"name": "Nombre B"},
        "CO.123",
        False,
    )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT to_regclass('public.whatsapp_contact_profiles')")
            )
            is not None
        )
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, first)
        assert (
            await session.scalar(
                text("SELECT profile_name FROM public.whatsapp_contact_profiles")
            )
            == "Nombre A"
        )
        assert (
            await session.scalar(
                text("SELECT phone_number FROM public.whatsapp_contact_profiles")
            )
            is None
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.whatsapp_contact_profiles WHERE tenant_id=:tenant"
                ),
                {"tenant": second},
            )
            == 0
        )


@pytest.mark.asyncio
async def test_existing_phonebook_is_safe_name_and_phone_fallback(session_factory):
    tenant, account = await seed(session_factory, "phonebook-fallback")
    conversation = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_contacts(id,tenant_id,whatsapp_account_id,customer_wa_id,full_name,provider_timestamp) VALUES(:id,:tenant,:account,'573000000001','Nombre en agenda',now())"
            ),
            {"id": uuid4(), "tenant": tenant, "account": account},
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES(:id,:tenant,:account,'573000000001')"
            ),
            {"id": conversation, "tenant": tenant, "account": account},
        )
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        result = await WorkspaceConversationService(session).get_conversation(
            tenant_id=tenant, conversation_id=conversation
        )
        assert result.contact_name == "Nombre en agenda"
        assert result.contact_phone_number == "+573000000001"


@pytest.mark.asyncio
async def test_same_sender_has_independent_profiles_in_two_accounts_of_one_company(
    session_factory,
):
    tenant, first_account = await seed(session_factory, "account-first")
    second_account = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts(id,tenant_id,provider,waba_id,phone_number_id,status) VALUES(:id,:tenant,'meta','waba-account-second','phone-account-second','active')"
            ),
            {"id": second_account, "tenant": tenant},
        )
    for label, name in (
        ("account-first", "Nombre en primera"),
        ("account-second", "Nombre en segunda"),
    ):
        await deliver(
            session_factory, label, f"wamid.{label}", 1787788800, {"name": name}
        )
    async with session_factory.begin() as session:
        for account in (first_account, second_account):
            await session.execute(
                text(
                    "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES(:id,:tenant,:account,'573000000001')"
                ),
                {"id": uuid4(), "tenant": tenant, "account": account},
            )
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        result = await WorkspaceConversationService(session).list_conversations(
            tenant_id=tenant
        )
        assert {item.account_id: item.contact_name for item in result.items} == {
            first_account: "Nombre en primera",
            second_account: "Nombre en segunda",
        }
