from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.modules.usage.models import Measurements, UsageEvent
from agents_factory.modules.usage.recorder import UsageRecorder


_PRODUCT = "private_originals"
_HOUR = timedelta(hours=1)


def completed_hour(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("storage_allocation_time_must_be_aware")
    value = now.astimezone(UTC)
    return value.replace(minute=0, second=0, microsecond=0)


class StorageUsageAllocator:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        recorder: UsageRecorder | None = None,
    ) -> None:
        self.sessions = sessions
        self.recorder = recorder or UsageRecorder(sessions)

    async def tenants(
        self, *, after: UUID | None = None, limit: int = 100
    ) -> list[UUID]:
        if not 1 <= limit <= 1000:
            raise ValueError("invalid_storage_allocation_limit")
        async with self.sessions.begin() as session:
            return list(
                (
                    await session.scalars(
                        text(
                            "SELECT id FROM public.tenants "
                            "WHERE (CAST(:after AS uuid) IS NULL OR id>:after) "
                            "ORDER BY id LIMIT :limit"
                        ),
                        {"after": after, "limit": limit},
                    )
                ).all()
            )

    async def record_next_completed_hour(
        self, *, context: TenantContext, through: datetime
    ) -> bool:
        end_limit = completed_hour(through)
        async with self.recorder.transaction(context) as session:
            latest = await session.scalar(
                text(
                    "SELECT max(occurred_at) FROM public.usage_records "
                    "WHERE tenant_id=:tenant AND kind='storage' "
                    "AND provider='agents_factory' AND product=:product "
                    "AND source_key LIKE 'storage:private_originals:%'"
                ),
                {"tenant": context.tenant_id, "product": _PRODUCT},
            )
            if latest is not None and latest >= end_limit:
                return False
            end = end_limit if latest is None else min(latest + _HOUR, end_limit)
            start = end - _HOUR
            row = (
                (
                    await session.execute(
                        text("""
                WITH media AS (
                  SELECT
                    coalesce(sum(byte_size::numeric * extract(epoch from
                      (least(coalesce(deleted_at,:end),:end)-greatest(stored_at,:start))) / 3600),0)
                      AS byte_hours,
                    coalesce(sum(byte_size) FILTER (
                      WHERE stored_at<:end AND (deleted_at IS NULL OR deleted_at>:end)),0)
                      AS current_bytes
                  FROM public.media_evidence
                  WHERE tenant_id=:tenant AND stored_at<:end
                    AND coalesce(deleted_at,:end)>:start
                ), knowledge_objects AS (
                  SELECT storage_path,max(byte_size) AS byte_size,
                    min(stored_at) AS stored_at
                  FROM public.knowledge_ingestions
                  WHERE tenant_id=:tenant AND stored_at<:end
                    AND storage_path IS NOT NULL
                  GROUP BY storage_path
                ), knowledge AS (
                  SELECT
                    coalesce(sum(byte_size::numeric * extract(epoch from
                      (:end-greatest(stored_at,:start))) / 3600),0) AS byte_hours,
                    coalesce(sum(byte_size),0) AS current_bytes
                  FROM knowledge_objects
                )
                SELECT media.byte_hours+knowledge.byte_hours AS byte_hours,
                  media.current_bytes+knowledge.current_bytes AS current_bytes
                FROM media CROSS JOIN knowledge
                """),
                        {"tenant": context.tenant_id, "start": start, "end": end},
                    )
                )
                .mappings()
                .one()
            )
            await self.recorder.record_in_session(
                session=session,
                context=context,
                event=UsageEvent(
                    source_key=(
                        f"storage:private_originals:{int(start.timestamp())}:"
                        f"{int(end.timestamp())}"
                    ),
                    occurred_at=end,
                    kind="storage",
                    provider="agents_factory",
                    product=_PRODUCT,
                    currency="USD",
                    measurements=Measurements(
                        storage_bytes=int(row["current_bytes"]),
                        storage_byte_hours=Decimal(row["byte_hours"]),
                    ),
                ),
            )
            return True
