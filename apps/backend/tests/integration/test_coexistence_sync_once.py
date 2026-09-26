from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from agents_factory.modules.whatsapp import sync_once


async def seed_account(session_factory, *, verified_at):
    tenant, account = uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id,slug,name) VALUES (:id,:slug,'Sync test')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id,tenant_id,provider,waba_id,phone_number_id,status,mode,coexistence_eligibility,verified_at) VALUES (:id,:tenant,'meta','sync-waba','123456','active','COEXISTENCE','ELIGIBLE',:verified_at)"
            ),
            {"id": account, "tenant": tenant, "verified_at": verified_at},
        )
    return tenant, account


async def test_sync_request_is_sent_once_and_retains_support_id(session_factory):
    tenant, account = await seed_account(session_factory, verified_at=datetime.now(UTC))
    calls = []

    async def send(phone, kind):
        calls.append((phone, kind))
        return "support-123"

    first = await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="history",
        send=send,
    )
    second = await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="history",
        send=send,
    )
    assert (first, second) == ("ACCEPTED", "ACCEPTED")
    assert calls == [("123456", "history")]
    async with session_factory.begin() as session:
        row = (
            await session.execute(
                text(
                    "SELECT state,request_id FROM public.whatsapp_sync_requests WHERE tenant_id=:tenant AND whatsapp_account_id=:account"
                ),
                {"tenant": tenant, "account": account},
            )
        ).one()
        assert row == ("ACCEPTED", "support-123")


async def test_uncertain_request_is_not_sent_twice(session_factory):
    tenant, account = await seed_account(session_factory, verified_at=datetime.now(UTC))
    calls = 0

    async def uncertain(phone, kind):
        nonlocal calls
        calls += 1
        raise RuntimeError("network outcome unknown")

    first = await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="smb_app_state_sync",
        send=uncertain,
    )
    second = await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="smb_app_state_sync",
        send=uncertain,
    )
    assert (first, second) == ("UNKNOWN", "UNKNOWN")
    assert calls == 1


async def test_expired_onboarding_cannot_start_one_shot_sync(session_factory):
    tenant, account = await seed_account(
        session_factory, verified_at=datetime.now(UTC) - timedelta(hours=25)
    )

    async def send(phone, kind):
        pytest.fail("expired account reached provider")

    with pytest.raises(ValueError, match="sync window"):
        await sync_once.request_sync_once(
            session_factory,
            tenant_id=tenant,
            account_id=account,
            sync_type="history",
            send=send,
        )
