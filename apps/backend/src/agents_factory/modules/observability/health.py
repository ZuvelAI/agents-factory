from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.database import set_tenant_context
from agents_factory.modules.observability.models import (
    ComponentHealth,
    HealthSnapshot,
    HealthState,
)


_STALE = timedelta(minutes=5)


class HealthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(
        self, *, tenant_id: UUID, now: datetime | None = None
    ) -> HealthSnapshot:
        observed_now = now or datetime.now(UTC)
        await set_tenant_context(self._session, tenant_id)
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT DISTINCT ON (name) name,status,error_code,occurred_at "
                        "FROM public.observability_events WHERE tenant_id=:tenant "
                        "AND event_kind='HEALTH' ORDER BY name,occurred_at DESC,id DESC"
                    ),
                    {"tenant": tenant_id},
                )
            )
            .mappings()
            .all()
        )
        components = tuple(
            ComponentHealth(
                component=str(row["name"]),
                state=cast(
                    HealthState,
                    "UNKNOWN"
                    if observed_now - row["occurred_at"] > _STALE
                    else str(row["status"]),
                ),
                observed_at=row["occurred_at"],
                reason_code=None
                if row["error_code"] is None
                else str(row["error_code"]),
            )
            for row in rows
        )
        state: HealthState = (
            "DOWN"
            if any(item.state == "DOWN" for item in components)
            else "DEGRADED"
            if any(item.state in {"DEGRADED", "UNKNOWN"} for item in components)
            else "HEALTHY"
            if components
            else "UNKNOWN"
        )
        return HealthSnapshot(
            generated_at=observed_now, state=state, components=components
        )
