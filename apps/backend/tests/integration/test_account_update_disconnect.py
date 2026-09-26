from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.ids import new_uuid7
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.webhook import (
    InvalidWebhookSignature,
    MetaWebhookProcessor,
)


WEBHOOK_SIGNING_MATERIAL = "account-update-test-fixture"
EVENT_TIME = 1739212624


def _body(*, event: str, phone: str | None = None, waba: str = "waba-shared") -> bytes:
    value: dict[str, str] = {"event": event}
    if phone is not None:
        value["phone_number"] = phone
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": waba,
                    "time": EVENT_TIME,
                    "changes": [
                        {
                            "field": "account_update",
                            "value": value,
                        }
                    ],
                }
            ],
        }
    ).encode()


async def _process(
    factory: async_sessionmaker[AsyncSession],
    body: bytes,
) -> None:
    signature = (
        "sha256="
        + hmac.new(WEBHOOK_SIGNING_MATERIAL.encode(), body, hashlib.sha256).hexdigest()
    )
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await MetaWebhookProcessor(
            session=session,
            provider=MetaCloudApiProvider(
                app_secret=SecretStr(WEBHOOK_SIGNING_MATERIAL)
            ),
        ).process(raw_body=body, signature=signature, correlation_id=new_uuid7())


async def _seed(
    factory: async_sessionmaker[AsyncSession],
    *,
    phone_id: str,
    display: str,
    verified_at: datetime,
) -> UUID:
    tenant_id, account_id = new_uuid7(), new_uuid7()
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:id, :slug, 'Account update test', 'active')"
            ),
            {"id": tenant_id, "slug": f"account-update-{tenant_id}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, "
                "display_phone_digits, mode, coexistence_eligibility, verified_at) "
                "VALUES (:id, :tenant_id, 'meta', 'waba-shared', :phone_id, "
                ":display, 'COEXISTENCE', 'ELIGIBLE', :verified_at)"
            ),
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "phone_id": phone_id,
                "display": display,
                "verified_at": verified_at,
            },
        )
    return account_id


async def _status(factory: async_sessionmaker[AsyncSession], account_id: UUID) -> str:
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        result = await session.scalar(
            text("SELECT status FROM public.whatsapp_accounts WHERE id = :id"),
            {"id": account_id},
        )
    assert isinstance(result, str)
    return result


async def _pending_alerts(
    factory: async_sessionmaker[AsyncSession], *, waba_id: str
) -> list[dict[str, object]]:
    async with factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        rows = await session.execute(
            text(
                "SELECT event, display_phone_digits, reason "
                "FROM agents_factory_private.whatsapp_account_update_alerts "
                "WHERE waba_id = :waba_id ORDER BY event, display_phone_digits"
            ),
            {"waba_id": waba_id},
        )
        return [dict(row) for row in rows.mappings().all()]


@pytest.mark.asyncio
async def test_partner_removed_deactivates_only_exact_waba_and_display_phone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    old = datetime(2025, 2, 9, tzinfo=UTC)
    target = await _seed(
        session_factory,
        phone_id=f"phone-{new_uuid7()}",
        display="573124009568",
        verified_at=old,
    )
    other = await _seed(
        session_factory,
        phone_id=f"phone-{new_uuid7()}",
        display="573124009569",
        verified_at=old,
    )

    await _process(
        session_factory, _body(event="PARTNER_REMOVED", phone="+57 312 400 9568")
    )
    await _process(
        session_factory, _body(event="PARTNER_REMOVED", phone="+57 312 400 9568")
    )

    assert await _status(session_factory, target) == "inactive"
    assert await _status(session_factory, other) == "active"


@pytest.mark.asyncio
async def test_old_partner_removed_does_not_disconnect_newer_registration(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account = await _seed(
        session_factory,
        phone_id=f"phone-{new_uuid7()}",
        display="573124009570",
        verified_at=datetime(2025, 2, 11, tzinfo=UTC),
    )

    await _process(
        session_factory, _body(event="PARTNER_REMOVED", phone="573124009570")
    )

    assert await _status(session_factory, account) == "active"


@pytest.mark.asyncio
async def test_unmatched_or_waba_wide_update_is_durably_queued_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for body in (
        _body(event="PARTNER_REMOVED", phone="573124009571"),
        _body(event="ACCOUNT_OFFBOARDED"),
        _body(event="ACCOUNT_RECONNECTED"),
    ):
        await _process(session_factory, body)
        await _process(session_factory, body)

    assert await _pending_alerts(session_factory, waba_id="waba-shared") == [
        {
            "event": "ACCOUNT_OFFBOARDED",
            "display_phone_digits": None,
            "reason": "unsupported_event",
        },
        {
            "event": "ACCOUNT_RECONNECTED",
            "display_phone_digits": None,
            "reason": "unsupported_event",
        },
        {
            "event": "PARTNER_REMOVED",
            "display_phone_digits": "573124009571",
            "reason": "unmatched",
        },
    ]


@pytest.mark.asyncio
async def test_partner_removed_cannot_cross_waba_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account = await _seed(
        session_factory,
        phone_id=f"phone-{new_uuid7()}",
        display="573124009572",
        verified_at=datetime(2025, 2, 9, tzinfo=UTC),
    )

    await _process(
        session_factory,
        _body(
            event="PARTNER_REMOVED",
            phone="573124009572",
            waba="other-waba",
        ),
    )

    assert await _status(session_factory, account) == "active"
    assert await _pending_alerts(session_factory, waba_id="other-waba") == [
        {
            "event": "PARTNER_REMOVED",
            "display_phone_digits": "573124009572",
            "reason": "unmatched",
        }
    ]


@pytest.mark.asyncio
async def test_invalid_signature_never_creates_an_account_update_alert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = _body(event="ACCOUNT_OFFBOARDED", waba="unsigned-waba")
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        with pytest.raises(InvalidWebhookSignature):
            await MetaWebhookProcessor(
                session=session,
                provider=MetaCloudApiProvider(
                    app_secret=SecretStr(WEBHOOK_SIGNING_MATERIAL)
                ),
            ).process(
                raw_body=body,
                signature="sha256=" + "0" * 64,
                correlation_id=new_uuid7(),
            )

    assert await _pending_alerts(session_factory, waba_id="unsigned-waba") == []


@pytest.mark.asyncio
async def test_pending_alerts_are_not_readable_by_webhook_or_public_roles(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _process(
        session_factory,
        _body(event="ACCOUNT_OFFBOARDED", waba="private-alert-waba"),
    )

    for role in ("agents_factory_app", "anon", "authenticated"):
        with pytest.raises(DBAPIError):
            async with session_factory.begin() as session:
                await session.execute(text(f"SET LOCAL ROLE {role}"))
                await session.execute(
                    text(
                        "SELECT event FROM "
                        "agents_factory_private.whatsapp_account_update_alerts"
                    )
                )
