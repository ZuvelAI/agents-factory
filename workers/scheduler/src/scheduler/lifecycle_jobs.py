from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.queue import JobEnvelope, JobHandler
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.approvals.expiry import close_request
from agents_factory.modules.approvals.repository import ApprovalRepository
from agents_factory.modules.handoffs.service import HandoffService
from agents_factory.modules.handoffs.surfaces import HumanSurfaceRegistry


class LifecycleJobs:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions = sessions
        self.now = now or (lambda: datetime.now(UTC))
        self.handoffs = HandoffService(
            sessions, surfaces=HumanSurfaceRegistry(), now=self.now
        )

    async def process(self, envelope: JobEnvelope) -> None:
        context = TenantContext(
            envelope.tenant_id, envelope.job_id, "system", envelope.job_id
        )
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(session, context.tenant_id)
            payload = await session.scalar(
                text(
                    "SELECT payload FROM public.outbox_jobs WHERE tenant_id=:tenant AND id=:id AND topic=:topic AND available_at<=:now"
                ),
                {
                    "tenant": context.tenant_id,
                    "id": envelope.job_id,
                    "topic": envelope.kind,
                    "now": self.now(),
                },
            )
            if not isinstance(payload, dict) or payload.get("aggregate_id") != str(
                envelope.aggregate_id
            ):
                raise ValueError("lifecycle_job_binding_mismatch")
            actions = ActionRepository(session, context)
            if envelope.kind == "actions.expire":
                action = await actions.get(envelope.aggregate_id, lock=True)
                if (
                    action is not None
                    and action.state == "AWAITING_CONFIRMATION"
                    and action.confirmation_expires_at is not None
                    and action.confirmation_expires_at <= self.now()
                ):
                    await actions.finish(
                        action=action,
                        target="EXPIRED",
                        result_payload=action.result,
                        finished_at=self.now(),
                    )
                    await AuditService(session).record(
                        context=context,
                        event_type="action.confirmation_expired",
                        entity_type="action",
                        entity_id=action.id,
                        payload={"state": "EXPIRED"},
                    )
                return
            if envelope.kind == "approvals.expire":
                repo = ApprovalRepository(session, context)
                snapshot = await repo.request(request_id=envelope.aggregate_id)
                if snapshot is None:
                    return
                # Same lock order as review/execution: Action -> route -> request.
                action = await actions.get(snapshot.action_id, lock=True)
                await repo.route(route_id=snapshot.route_id, lock=" FOR SHARE")
                request = await repo.request(request_id=snapshot.id, locked=True)
                if (
                    action is not None
                    and request is not None
                    and request.state == "PENDING"
                    and request.expires_at <= self.now()
                ):
                    await close_request(repo, request, action, "EXPIRED", self.now())
                return
            if envelope.kind != "handoffs.inactivity":
                raise ValueError("invalid_lifecycle_job")
        await self.handoffs.close_if_inactive(
            context=context, handoff_id=envelope.aggregate_id
        )


def configure_lifecycle_jobs(context: dict[Any, Any], *, database: Database) -> None:
    service = context.get("lifecycle_jobs") or LifecycleJobs(database.session_factory)
    if not isinstance(service, LifecycleJobs):
        raise ValueError("invalid_lifecycle_service")
    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers.update(
        dict.fromkeys(
            ("actions.expire", "approvals.expire", "handoffs.inactivity"),
            service.process,
        )
    )
