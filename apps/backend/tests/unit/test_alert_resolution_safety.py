from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.security import AdminPrincipal, require_platform_admin
from agents_factory.database import Database
from agents_factory.dependencies import get_transaction
from agents_factory.main import create_app
from agents_factory.modules.whatsapp.alert_router import (
    ResolveAccountUpdateAlertRequest,
)


SYNTHETIC_NOTE = "private-review-note-sentinel"


class FailingSession:
    async def scalar(self, *_args: Any, **_kwargs: Any) -> int:
        return 1

    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise DBAPIError(
            "INSERT INTO alert_resolutions VALUES (:note)",
            {"note": SYNTHETIC_NOTE},
            RuntimeError(f"Database rejected {SYNTHETIC_NOTE}"),
        )


@pytest.mark.parametrize("note", ["review\x00end", "review\ud800end"])
def test_note_rejects_database_incompatible_text(note: str) -> None:
    with pytest.raises(ValidationError):
        ResolveAccountUpdateAlertRequest(note=note)


@pytest.mark.asyncio
async def test_database_hides_bound_values_in_engine_errors() -> None:
    database = Database(SecretStr("postgresql+asyncpg://test:test@localhost/test"))
    try:
        assert database.session_factory.kw["bind"].sync_engine.hide_parameters is True
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_alert_database_failure_does_not_escape_or_log_note(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app()

    async def session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, FailingSession())

    async def admin() -> AdminPrincipal:
        return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.dependency_overrides[get_transaction] = session
    app.dependency_overrides[require_platform_admin] = admin

    # ASGI servers log exceptions that escape the app, including their chains.
    async def server(scope: Any, receive: Any, send: Any) -> None:
        try:
            await app(scope, receive, send)
        except Exception:
            logging.getLogger("alert-test-asgi-server").exception(
                "Unhandled ASGI error"
            )
            raise

    caplog.set_level(logging.ERROR)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/admin/whatsapp/account-update-alerts/{uuid4()}/resolve",
            json={"note": SYNTHETIC_NOTE},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "whatsapp_alert_storage_unavailable"
    assert SYNTHETIC_NOTE not in response.text
    assert SYNTHETIC_NOTE not in caplog.text


@pytest.mark.parametrize("note", ["review\x00end", "review\ud800end"])
@pytest.mark.asyncio
async def test_invalid_note_response_does_not_echo_input(note: str) -> None:
    app = create_app()

    async def session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, FailingSession())

    async def admin() -> AdminPrincipal:
        return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.dependency_overrides[get_transaction] = session
    app.dependency_overrides[require_platform_admin] = admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/admin/whatsapp/account-update-alerts/{uuid4()}/resolve",
            content=json.dumps({"note": note}),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert "review" not in response.text
