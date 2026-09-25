import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.webhook import MetaWebhookProcessor


async def seed(session_factory, label):
    tenant, account = uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES (:id, :slug, 'Contact sync test')"
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


async def deliver(session_factory, label, action, timestamp, name="Cliente"):
    contact = {"phone_number": "573000000001"}
    if action == "add":
        contact.update(full_name=name, first_name=name)
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": f"waba-{label}",
                    "changes": [
                        {
                            "field": "smb_app_state_sync",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": f"phone-{label}"},
                                "state_sync": [
                                    {
                                        "type": "contact",
                                        "action": action,
                                        "contact": contact,
                                        "metadata": {"timestamp": str(timestamp)},
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
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        return await MetaWebhookProcessor(
            session=session,
            provider=MetaCloudApiProvider(app_secret=SecretStr("test-only")),
        ).process(raw_body=body, signature=signature, correlation_id=uuid4())


async def test_contact_sync_persists_without_triggering_ai(session_factory):
    tenant, account = await seed(session_factory, "add")
    await deliver(session_factory, "add", "add", 1700255121, "Nombre inicial")
    await deliver(session_factory, "add", "add", 1700255122, "Nombre actualizado")
    await deliver(session_factory, "add", "add", 1700255122, "Nombre actualizado")
    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT tenant_id, whatsapp_account_id, customer_wa_id, full_name, is_deleted FROM public.whatsapp_contacts"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert dict(row) == {
            "tenant_id": tenant,
            "whatsapp_account_id": account,
            "customer_wa_id": "573000000001",
            "full_name": "Nombre actualizado",
            "is_deleted": False,
        }
        assert await session.scalar(text("SELECT count(*) FROM public.messages")) == 0
        assert (
            await session.scalar(text("SELECT count(*) FROM public.outbox_jobs")) == 0
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE event_type='whatsapp.contact.synced'"
                )
            )
            == 2
        )


@pytest.mark.parametrize("old_add_first", [True, False])
async def test_removed_contact_cannot_be_resurrected_by_stale_or_equal_timestamp_add(
    session_factory, old_add_first
):
    await seed(session_factory, "remove")
    if old_add_first:
        await deliver(session_factory, "remove", "add", 1700255122)
    await deliver(session_factory, "remove", "remove", 1700255122)
    await deliver(session_factory, "remove", "add", 1700255121)
    await deliver(session_factory, "remove", "add", 1700255122)
    await deliver(session_factory, "remove", "remove", 1700255122)
    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT is_deleted, full_name, first_name FROM public.whatsapp_contacts"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert dict(row) == {"is_deleted": True, "full_name": None, "first_name": None}


async def test_contact_sync_is_tenant_isolated(session_factory):
    first, _ = await seed(session_factory, "first")
    second, _ = await seed(session_factory, "second")
    await deliver(session_factory, "first", "add", 1700255121, "Nombre A")
    await deliver(session_factory, "second", "add", 1700255121, "Nombre B")
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, first)
        assert (
            await session.scalar(text("SELECT full_name FROM public.whatsapp_contacts"))
            == "Nombre A"
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.whatsapp_contacts WHERE tenant_id=:tenant"
                ),
                {"tenant": second},
            )
            == 0
        )
