from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agents_factory.common.errors import DomainError
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession


class SafeAlertRoute(APIRoute):
    """Keep operator notes out of validation replies and ASGI exception logs."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(
                    status_code=422, detail="Invalid alert request"
                ) from None
            except SQLAlchemyError:
                # Driver errors may contain both bound values and server DETAIL.
                # A handled domain error prevents the raw exception reaching ASGI.
                raise DomainError(
                    type="https://agents-factory.dev/problems/whatsapp-alert-storage-unavailable",
                    title="WhatsApp alert storage unavailable",
                    status=503,
                    detail="The alert could not be read or saved. Try again later.",
                    code="whatsapp_alert_storage_unavailable",
                ) from None

        return handle


router = APIRouter(
    prefix="/admin/whatsapp",
    tags=["platform-admin-whatsapp"],
    route_class=SafeAlertRoute,
)


class AccountUpdateAlert(BaseModel):
    id: UUID
    waba_id: str
    event: str
    display_phone_digits: str | None
    occurred_at: datetime
    reason: str
    received_at: datetime
    resolved_at: datetime | None
    resolved_by: UUID | None
    resolution_note: str | None


class AccountUpdateAlertSummary(BaseModel):
    open_count: int


class ResolveAccountUpdateAlertRequest(BaseModel):
    note: str

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        note = value.strip()
        if not 1 <= len(note) <= 500:
            raise ValueError("The resolution note must contain 1 to 500 characters")
        if "\x00" in note or any(
            0xD800 <= ord(character) <= 0xDFFF for character in note
        ):
            raise ValueError("The resolution note must be valid database text")
        return note


class AccountUpdateAlertResolution(BaseModel):
    alert_id: UUID
    resolved_by: UUID
    resolution_note: str
    resolved_at: datetime


@router.get("/account-update-alerts")
async def list_account_update_alerts(
    principal: PlatformAdmin,
    session: TransactionSession,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Literal["open", "resolved"] | None = Query(default=None),
) -> list[AccountUpdateAlert]:
    """Inspect signed, ambiguous Meta account updates without changing account state."""
    del principal
    status_filter = {
        None: "",
        "open": "WHERE r.alert_id IS NULL ",
        "resolved": "WHERE r.alert_id IS NOT NULL ",
    }[status]
    result = await session.execute(
        text(
            "SELECT a.id, a.waba_id, a.event, a.display_phone_digits, "
            "a.occurred_at, a.reason, a.received_at, "
            "r.resolved_at, r.resolved_by, r.resolution_note "
            "FROM agents_factory_private.whatsapp_account_update_alerts a "
            "LEFT JOIN agents_factory_private.whatsapp_account_update_alert_resolutions r "
            "ON r.alert_id = a.id "
            + status_filter
            + "ORDER BY a.received_at DESC, a.id DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    )
    return [AccountUpdateAlert.model_validate(dict(row)) for row in result.mappings()]


@router.get("/account-update-alerts/summary")
async def get_account_update_alert_summary(
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AccountUpdateAlertSummary:
    del principal
    count = await session.scalar(
        text(
            "SELECT count(*) FROM agents_factory_private.whatsapp_account_update_alerts a "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM agents_factory_private.whatsapp_account_update_alert_resolutions r "
            "WHERE r.alert_id = a.id)"
        )
    )
    return AccountUpdateAlertSummary(open_count=int(count or 0))


@router.post("/account-update-alerts/{alert_id}/resolve")
async def resolve_account_update_alert(
    alert_id: UUID,
    request: ResolveAccountUpdateAlertRequest,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AccountUpdateAlertResolution:
    exists = await session.scalar(
        text(
            "SELECT 1 FROM agents_factory_private.whatsapp_account_update_alerts "
            "WHERE id = :alert_id"
        ),
        {"alert_id": alert_id},
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    result = await session.execute(
        text(
            "INSERT INTO agents_factory_private.whatsapp_account_update_alert_resolutions "
            "(alert_id, resolved_by, resolution_note) "
            "VALUES (:alert_id, :resolved_by, :resolution_note) "
            "ON CONFLICT (alert_id) DO NOTHING "
            "RETURNING alert_id, resolved_by, resolution_note, resolved_at"
        ),
        {
            "alert_id": alert_id,
            "resolved_by": principal.user_id,
            "resolution_note": request.note,
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=409, detail="Alert already resolved")
    return AccountUpdateAlertResolution.model_validate(dict(row))
