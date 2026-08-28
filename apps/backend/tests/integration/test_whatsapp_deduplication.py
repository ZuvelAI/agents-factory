from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.ids import new_uuid7
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.webhook import (
    MetaWebhookProcessor,
    UnknownAccountMapping,
)


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "meta" / "inbound_text.json"
)
APP_SECRET = "meta-app-secret-test-value"


def _signature(raw_body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _seed_mapping(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = new_uuid7()
    account_id = new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:tenant_id, 'whatsapp-tenant', 'WhatsApp Tenant', 'active')"
            ),
            {"tenant_id": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, status) "
                "VALUES (:id, :tenant_id, 'meta', 'waba_test_001', "
                "'phone_number_test_001', 'active')"
            ),
            {"id": account_id, "tenant_id": tenant_id},
        )


@pytest.mark.asyncio
async def test_one_hundred_replays_create_one_event_and_one_outbox_intent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_mapping(session_factory)
    raw_body = FIXTURE.read_bytes()
    signature = _signature(raw_body)
    accepted = 0
    duplicates = 0

    for _ in range(100):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            result = await MetaWebhookProcessor(
                session=session,
                provider=MetaCloudApiProvider(app_secret=SecretStr(APP_SECRET)),
            ).process(
                raw_body=raw_body,
                signature=signature,
                correlation_id=new_uuid7(),
            )
            accepted += result.accepted_messages
            duplicates += result.duplicate_messages

    async with session_factory.begin() as session:
        event_count = await session.scalar(
            text("SELECT count(*) FROM public.whatsapp_webhook_events")
        )
        outbox_count = await session.scalar(
            text(
                "SELECT count(*) FROM public.outbox_jobs "
                "WHERE topic = 'whatsapp.inbound.received'"
            )
        )

    assert accepted == 1
    assert duplicates == 99
    assert event_count == 1
    assert outbox_count == 1


@pytest.mark.asyncio
async def test_unknown_account_mapping_fails_closed_and_persists_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    raw_body = FIXTURE.read_bytes()

    with pytest.raises(UnknownAccountMapping):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await MetaWebhookProcessor(
                session=session,
                provider=MetaCloudApiProvider(app_secret=SecretStr(APP_SECRET)),
            ).process(
                raw_body=raw_body,
                signature=_signature(raw_body),
                correlation_id=new_uuid7(),
            )

    async with session_factory.begin() as session:
        event_count = await session.scalar(
            text("SELECT count(*) FROM public.whatsapp_webhook_events")
        )
        outbox_count = await session.scalar(
            text(
                "SELECT count(*) FROM public.outbox_jobs "
                "WHERE topic = 'whatsapp.inbound.received'"
            )
        )

    assert event_count == 0
    assert outbox_count == 0
