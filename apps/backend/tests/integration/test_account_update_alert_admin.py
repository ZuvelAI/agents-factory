from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
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


def admin_app(
    session_factory: async_sessionmaker[AsyncSession], admin_id: UUID | None = None
) -> FastAPI:
    app = create_app()

    async def transaction() -> AsyncIterator[AsyncSession]:
        async with session_factory.begin() as session:
            yield session

    async def admin(session: TransactionSession) -> AdminPrincipal:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return AdminPrincipal(user_id=admin_id or uuid4(), session_id=uuid4())

    app.dependency_overrides[get_transaction] = transaction
    app.dependency_overrides[require_platform_admin] = admin
    return app


async def seed_alert(
    session_factory: async_sessionmaker[AsyncSession], *, waba_id: str
) -> UUID:
    alert_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO agents_factory_private.whatsapp_account_update_alerts "
                "(id, event_fingerprint, waba_id, event, occurred_at, reason) "
                "VALUES (:id, :fingerprint, :waba_id, 'ACCOUNT_OFFBOARDED', "
                ":occurred_at, 'unsupported_event')"
            ),
            {
                "id": alert_id,
                "fingerprint": uuid4().hex * 2,
                "waba_id": waba_id,
                "occurred_at": datetime.now(UTC),
            },
        )
    return alert_id


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


@pytest.mark.asyncio
async def test_alert_list_filters_without_changing_default(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await seed_alert(session_factory, waba_id="first")
    second = await seed_alert(session_factory, waba_id="second")
    app = admin_app(session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        closed = await client.post(
            f"/admin/whatsapp/account-update-alerts/{first}/resolve",
            json={"note": "Checked in Meta"},
        )
        default = await client.get("/admin/whatsapp/account-update-alerts")
        opened = await client.get("/admin/whatsapp/account-update-alerts?status=open")
        resolved = await client.get(
            "/admin/whatsapp/account-update-alerts?status=resolved"
        )
        invalid = await client.get("/admin/whatsapp/account-update-alerts?status=other")

    assert closed.status_code == 200
    assert invalid.status_code == 422
    assert {item["id"] for item in default.json()} == {str(first), str(second)}
    assert [item["id"] for item in opened.json()] == [str(second)]
    assert [item["id"] for item in resolved.json()] == [str(first)]
    assert opened.json()[0]["resolution_note"] is None
    assert resolved.json()[0]["resolution_note"] == "Checked in Meta"
    assert resolved.json()[0]["resolved_at"] is not None
    assert resolved.json()[0]["resolved_by"] is not None
    assert all("event_fingerprint" not in item for item in default.json())
    assert all("payload" not in item for item in default.json())


@pytest.mark.asyncio
async def test_alert_summary_counts_only_open(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await seed_alert(session_factory, waba_id="first")
    await seed_alert(session_factory, waba_id="second")
    app = admin_app(session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        before = await client.get("/admin/whatsapp/account-update-alerts/summary")
        await client.post(
            f"/admin/whatsapp/account-update-alerts/{first}/resolve",
            json={"note": "Reviewed"},
        )
        after = await client.get("/admin/whatsapp/account-update-alerts/summary")

    assert before.json() == {"open_count": 2}
    assert after.json() == {"open_count": 1}


@pytest.mark.asyncio
async def test_resolve_requires_platform_admin(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    alert_id = await seed_alert(session_factory, waba_id="auth")
    app = create_app()

    async def transaction() -> AsyncIterator[AsyncSession]:
        async with session_factory.begin() as session:
            yield session

    app.dependency_overrides[get_transaction] = transaction
    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(FakeVerifier())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.post(
            f"/admin/whatsapp/account-update-alerts/{alert_id}/resolve",
            json={"note": "Unauthorized"},
        )
        unlisted = await client.post(
            f"/admin/whatsapp/account-update-alerts/{alert_id}/resolve",
            headers={"Authorization": "Bearer unlisted-admin"},
            json={"note": "Unauthorized"},
        )
        summary_missing = await client.get(
            "/admin/whatsapp/account-update-alerts/summary"
        )

    assert missing.status_code == 401
    assert unlisted.status_code == 403
    assert summary_missing.status_code == 401


@pytest.mark.asyncio
async def test_resolve_rejects_invalid_note(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    alert_id = await seed_alert(session_factory, waba_id="invalid-note")
    app = admin_app(session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for note in ("", " \t ", "x" * 501):
            response = await client.post(
                f"/admin/whatsapp/account-update-alerts/{alert_id}/resolve",
                json={"note": note},
            )
            assert response.status_code == 422
        summary = await client.get("/admin/whatsapp/account-update-alerts/summary")
    assert summary.json() == {"open_count": 1}


@pytest.mark.asyncio
async def test_resolve_unknown_or_invalid_alert_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    existing = await seed_alert(session_factory, waba_id="untouched")
    app = admin_app(session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        unknown = await client.post(
            f"/admin/whatsapp/account-update-alerts/{uuid4()}/resolve",
            json={"note": "Reviewed"},
        )
        malformed = await client.post(
            "/admin/whatsapp/account-update-alerts/not-a-uuid/resolve",
            json={"note": "Reviewed"},
        )
        opened = await client.get("/admin/whatsapp/account-update-alerts?status=open")
    assert unknown.status_code == 404
    assert malformed.status_code == 422
    assert [item["id"] for item in opened.json()] == [str(existing)]


@pytest.mark.asyncio
async def test_resolve_concurrent_one_winner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    alert_id = await seed_alert(session_factory, waba_id="race")
    actor_a, actor_b = uuid4(), uuid4()
    app_a = admin_app(session_factory, actor_a)
    app_b = admin_app(session_factory, actor_b)
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_a), base_url="http://a"
        ) as client_a,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_b), base_url="http://b"
        ) as client_b,
    ):
        results = await asyncio.gather(
            client_a.post(
                f"/admin/whatsapp/account-update-alerts/{alert_id}/resolve",
                json={"note": "First actor"},
            ),
            client_b.post(
                f"/admin/whatsapp/account-update-alerts/{alert_id}/resolve",
                json={"note": "Second actor"},
            ),
        )
        history = await client_a.get(
            "/admin/whatsapp/account-update-alerts?status=resolved"
        )

    assert sorted(response.status_code for response in results) == [200, 409]
    winner = next(
        response.json() for response in results if response.status_code == 200
    )
    assert winner["resolved_by"] in {str(actor_a), str(actor_b)}
    assert winner["resolution_note"] in {"First actor", "Second actor"}
    assert len(history.json()) == 1
    assert history.json()[0]["resolution_note"] == winner["resolution_note"]
    assert history.json()[0]["resolved_by"] == winner["resolved_by"]


@pytest.mark.asyncio
async def test_alert_retry_does_not_reopen_resolution(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    occurred_at = datetime(2025, 3, 1, tzinfo=UTC)

    async def queue(when: datetime) -> None:
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await WhatsAppWebhookRepository(session).queue_account_update_alert(
                waba_id="waba-retry",
                event="ACCOUNT_OFFBOARDED",
                display_phone_digits=None,
                occurred_at=when,
                reason="unsupported_event",
            )

    await queue(occurred_at)
    app = admin_app(session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        initial = await client.get("/admin/whatsapp/account-update-alerts")
        alert_id = initial.json()[0]["id"]
        closed = await client.post(
            f"/admin/whatsapp/account-update-alerts/{alert_id}/resolve",
            json={"note": "Confirmed old account update"},
        )
        await queue(occurred_at)
        after_retry = await client.get("/admin/whatsapp/account-update-alerts/summary")
        await queue(datetime(2025, 3, 2, tzinfo=UTC))
        after_new_event = await client.get(
            "/admin/whatsapp/account-update-alerts/summary"
        )
        history = await client.get(
            "/admin/whatsapp/account-update-alerts?status=resolved"
        )

    assert closed.status_code == 200
    assert after_retry.json() == {"open_count": 0}
    assert after_new_event.json() == {"open_count": 1}
    assert len(history.json()) == 1
    assert history.json()[0]["id"] == alert_id
    async with session_factory.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.whatsapp_accounts"))
            == 0
        )
        assert (
            await session.scalar(text("SELECT count(*) FROM public.agent_instances"))
            == 0
        )
