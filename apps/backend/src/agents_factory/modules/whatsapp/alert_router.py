from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
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


@router.get("/account-update-alerts")
async def list_account_update_alerts(
    principal: PlatformAdmin,
    session: TransactionSession,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AccountUpdateAlert]:
    """Inspect only signed, ambiguous Meta account updates; never resolve them here."""
    del principal
    result = await session.execute(
        text(
            "SELECT id, waba_id, event, display_phone_digits, occurred_at, "
            "reason, received_at "
            "FROM agents_factory_private.whatsapp_account_update_alerts "
            "ORDER BY received_at DESC, id DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    )
    return [AccountUpdateAlert.model_validate(dict(row)) for row in result.mappings()]
