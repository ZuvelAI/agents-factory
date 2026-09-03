from typing import Any, cast

from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import JobEnvelope, JobHandler
from agents_factory.modules.approvals.execution import ApprovalExecutionService


def configure_approval_execution(context: dict[Any, Any]) -> None:
    service = context.get("approval_execution_service")
    if not isinstance(service, ApprovalExecutionService):
        return

    async def process(envelope: JobEnvelope) -> None:
        actor = TenantContext(
            envelope.tenant_id, envelope.job_id, "system", envelope.job_id
        )
        # An envelope is only a locator. Bind it to the tenant's durable outbox,
        # then reload approval/Action authority from PostgreSQL, never its payload.
        async with service.sessions.begin() as session:
            await service._scope(session, actor)
            payload = await session.scalar(
                text(
                    "SELECT payload FROM public.outbox_jobs WHERE tenant_id=:tenant AND id=:id AND topic=:topic"
                ),
                {
                    "tenant": actor.tenant_id,
                    "id": envelope.job_id,
                    "topic": envelope.kind,
                },
            )
        if not isinstance(payload, dict) or payload.get("aggregate_id") != str(
            envelope.aggregate_id
        ):
            raise ValueError("approval_job_binding_mismatch")
        if envelope.kind == "approvals.execute":
            await service.execute(context=actor, action_id=envelope.aggregate_id)
        elif envelope.kind in {"approvals.result", "approvals.result.held"}:
            await service.notify(context=actor, action_id=envelope.aggregate_id)
        else:
            raise ValueError("invalid_approval_execution_job")

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers.update(
        dict.fromkeys(
            ("approvals.execute", "approvals.result", "approvals.result.held"), process
        )
    )
