from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import text

from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession


router = APIRouter(prefix="/admin/whatsapp", tags=["platform-admin-whatsapp"])


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
