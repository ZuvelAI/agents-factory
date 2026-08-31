import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.observability.scheduled_events import schedule_once


def reminder_instant(start: datetime, minutes_before: int) -> datetime:
    # Subtract elapsed time in UTC; local wall-time arithmetic is wrong across DST.
    return start.astimezone(UTC) - timedelta(minutes=minutes_before)


class LifecycleScanner:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime] | None = None,
        retention_enabled: bool = False,
    ) -> None:
        self.sessions = sessions
        self.now = now or (lambda: datetime.now(UTC))
        self.retention_enabled = retention_enabled

    async def scan_tenant(self, tenant_id: UUID, *, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("invalid_scan_limit")
        now = self.now().astimezone(UTC)
        context = TenantContext(tenant_id, new_uuid7(), "system", new_uuid7())
        key = int.from_bytes(
            hashlib.sha256(f"lifecycle-scan:{tenant_id}".encode()).digest()[:8],
            "big",
            signed=True,
        )
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(session, tenant_id)
            if not await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}
            ):
                return 0
            # The durable outbox owns dispatch/retry claims. Source rows are only
            # candidates; each handler revalidates state/deadline under its lock.
            # Match the original deadline, not mutable retry available_at, so an
            # already scheduled row cannot consume every bounded scan slot.
            candidates = (
                (
                    await session.execute(
                        text("""
                WITH due AS (
                  SELECT 'cases.timer' AS topic,c.id AS aggregate_id,c.close_at AS due_at,
                    'case' AS kind, NULL::integer AS revision,NULL::uuid AS action_id
                  FROM public.cases c WHERE c.tenant_id=:tenant AND c.status='RESOLVED' AND c.close_at<=:now
                  UNION ALL
                  SELECT 'cases.timer',c.id,c.approaching_at,'case',NULL,NULL FROM public.cases c
                  WHERE c.tenant_id=:tenant AND c.status NOT IN ('RESOLVED','CLOSED','REJECTED','CANCELLED','EXPIRED','DUPLICATE')
                    AND c.target_status='ON_TRACK' AND c.approaching_at<=:now AND c.target_at>:now
                  UNION ALL
                  SELECT 'cases.timer',c.id,c.target_at,'case',NULL,NULL FROM public.cases c
                  WHERE c.tenant_id=:tenant AND c.status NOT IN ('RESOLVED','CLOSED','REJECTED','CANCELLED','EXPIRED','DUPLICATE')
                    AND c.target_status<>'OVERDUE' AND c.target_at<=:now
                  UNION ALL
                  SELECT 'approvals.expire',r.id,r.expires_at,'approval',NULL,r.action_id
                  FROM public.approval_requests r WHERE r.tenant_id=:tenant AND r.state='PENDING' AND r.expires_at<=:now
                  UNION ALL
                  SELECT 'actions.expire',a.id,a.confirmation_expires_at,'action',NULL,a.id
                  FROM public.actions a WHERE a.tenant_id=:tenant AND a.state='AWAITING_CONFIRMATION' AND a.confirmation_expires_at<=:now
                  UNION ALL
                  SELECT 'handoffs.inactivity',h.id,
                    greatest(h.last_activity_at,coalesce((SELECT max(m.created_at) FROM public.messages m
                      WHERE m.tenant_id=h.tenant_id AND m.conversation_id=h.conversation_id AND m.direction='inbound' AND m.sender_type='customer'),h.last_activity_at))
                      + make_interval(hours=>(h.configuration->>'inactivity_hours')::integer),
                    'handoff',NULL,NULL
                  FROM public.handoffs h WHERE h.tenant_id=:tenant AND h.status<>'CLOSED'
                  UNION ALL
                  SELECT 'appointments.notify',a.id,
                    a.start_at-make_interval(mins=>(c.configuration->'communications'->>'reminder_minutes_before')::integer),
                    'reminder',a.revision,a.last_action_id
                  FROM public.appointments a JOIN public.appointment_configurations c ON c.tenant_id=a.tenant_id
                  WHERE a.tenant_id=:tenant AND a.status='BOOKED' AND a.start_at>:now
                )
                SELECT * FROM due d WHERE d.due_at<=:now AND NOT EXISTS (
                  SELECT 1 FROM public.outbox_jobs j WHERE j.tenant_id=:tenant AND j.topic=d.topic
                  AND j.payload->>'aggregate_id'=d.aggregate_id::text
                  AND (CASE WHEN d.kind='approval' THEN true
                    WHEN d.kind='reminder' THEN
                    j.payload->>'kind'='reminder' AND j.payload->>'revision'=d.revision::text
                      AND coalesce((j.payload->>'scheduled_for')::timestamptz,j.available_at)=d.due_at
                    ELSE coalesce((j.payload->>'scheduled_for')::timestamptz,
                      CASE WHEN d.kind='case' THEN substring(j.idempotency_key from '^case-timer:[^:]+:(.*)$')::timestamptz END,
                      j.available_at)=d.due_at END)
                ) AND (d.kind<>'reminder' OR NOT EXISTS (
                  SELECT 1 FROM public.outbound_messages o WHERE o.tenant_id=:tenant
                  AND o.idempotency_key='appointments.notify:'||d.aggregate_id::text||':'||d.revision::text||':'||'reminder'
                )) ORDER BY due_at,topic,aggregate_id LIMIT :limit
            """),
                        {"tenant": tenant_id, "now": now, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
            created = 0
            for row in candidates:
                aggregate, due = row["aggregate_id"], row["due_at"]
                payload: dict[str, object] = {}
                if row["kind"] == "case":
                    identity = f"case-timer:{aggregate}:{due.isoformat()}"
                elif row["kind"] == "approval":
                    identity = f"approvals.expire:{aggregate}"
                elif row["kind"] == "reminder":
                    identity = f"appointments.notify:{aggregate}:{row['revision']}:reminder:timing:{due.isoformat()}"
                    payload = {
                        "appointment_id": str(aggregate),
                        "revision": row["revision"],
                        "kind": "reminder",
                        "action_id": str(row["action_id"]),
                    }
                else:
                    identity = f"{row['topic']}:{aggregate}:{due.isoformat()}"
                created += await schedule_once(
                    session,
                    context=context,
                    topic=row["topic"],
                    aggregate_id=aggregate,
                    due_at=due,
                    idempotency_key=identity,
                    payload=payload,
                )
            if self.retention_enabled:
                minute = now.replace(second=0, microsecond=0)
                created += await schedule_once(
                    session,
                    context=context,
                    topic="retention.cleanup",
                    aggregate_id=tenant_id,
                    due_at=minute,
                    idempotency_key=f"retention.cleanup:{tenant_id}:{minute.isoformat()}",
                )
            return created

    async def tenants(
        self, *, after: UUID | None = None, limit: int = 100
    ) -> list[UUID]:
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            return list(
                (
                    await session.scalars(
                        text(
                            "SELECT id FROM public.tenants WHERE (CAST(:after AS uuid) IS NULL OR id>:after) ORDER BY id LIMIT :limit"
                        ),
                        {"after": after, "limit": limit},
                    )
                ).all()
            )
