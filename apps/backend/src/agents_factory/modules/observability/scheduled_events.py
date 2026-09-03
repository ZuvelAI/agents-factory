from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.outbox import OutboxService


async def schedule_once(
    session: AsyncSession,
    *,
    context: TenantContext,
    topic: str,
    aggregate_id: UUID,
    due_at: datetime,
    idempotency_key: str,
    payload: dict[str, object] | None = None,
) -> bool:
    """The caller owns a short tenant scan lock. Reuse native domain timer keys."""
    exists = await session.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM public.outbox_jobs WHERE tenant_id=:tenant "
            "AND idempotency_key=:key)"
        ),
        {"tenant": context.tenant_id, "key": idempotency_key},
    )
    if exists:
        return False
    await OutboxService(session).enqueue(
        context=context,
        topic=topic,
        idempotency_key=idempotency_key,
        available_at=due_at,
        payload={
            **(payload or {}),
            "aggregate_id": str(aggregate_id),
            "scheduled_for": due_at.isoformat(),
        },
    )
    await AuditService(session).record(
        context=context,
        event_type="schedule.intent_created",
        entity_type="scheduled_entity",
        entity_id=aggregate_id,
        payload={"topic": topic, "due_at": due_at.isoformat()},
    )
    return True
