from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.security import (
    AdminPrincipal,
    PlatformAdminAuthorizer,
    require_platform_admin,
)
from agents_factory.dependencies import TransactionSession, get_transaction
from agents_factory.main import create_app
from agents_factory.modules.whatsapp.repository import WhatsAppWebhookRepository


class FakeVerifier:
    async def verify(self, access_jwt: str) -> AdminPrincipal:
        assert access_jwt == "unlisted-admin"
        return AdminPrincipal(user_id=uuid4(), session_id=uuid4())


@pytest.mark.asyncio
async def test_account_update_alerts_require_platform_admin(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = create_app()

    async def transaction() -> AsyncIterator[AsyncSession]:
        async with session_factory.begin() as session:
            yield session

    app.dependency_overrides[get_transaction] = transaction
    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(FakeVerifier())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/admin/whatsapp/account-update-alerts")
        unlisted = await client.get(
            "/admin/whatsapp/account-update-alerts",
            headers={"Authorization": "Bearer unlisted-admin"},
        )

    assert response.status_code == 401
    assert unlisted.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_can_read_bounded_account_update_alerts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        repository = WhatsAppWebhookRepository(session)
        for index in range(3):
            await repository.queue_account_update_alert(
                waba_id=f"waba-{index}",
                event="ACCOUNT_OFFBOARDED",
                display_phone_digits=None,
                occurred_at=datetime(2025, 2, 10 + index, tzinfo=UTC),
                reason="unsupported_event",
            )

    app = create_app()

    async def transaction() -> AsyncIterator[AsyncSession]:
        async with session_factory.begin() as session:
            yield session

    async def admin(session: TransactionSession) -> AdminPrincipal:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.dependency_overrides[get_transaction] = transaction
    app.dependency_overrides[require_platform_admin] = admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/admin/whatsapp/account-update-alerts?limit=2")
        invalid = await client.get("/admin/whatsapp/account-update-alerts?limit=101")

    assert response.status_code == 200
    assert invalid.status_code == 422
    alerts = response.json()
    assert len(alerts) == 2
    assert {alert["waba_id"] for alert in alerts} == {"waba-1", "waba-2"}
    assert all(alert["reason"] == "unsupported_event" for alert in alerts)
    assert all("event_fingerprint" not in alert for alert in alerts)
