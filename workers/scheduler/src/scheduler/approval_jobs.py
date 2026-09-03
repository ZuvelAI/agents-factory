from typing import Any, Literal, cast

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import JobEnvelope, JobHandler
from agents_factory.modules.approvals.service import ApprovalService
from agents_factory.modules.approvals.execution import ApprovalExecutionService


def configure_approval_jobs(
    context: dict[Any, Any],
) -> dict[str, Literal["scheduler", "agent"]]:
    # A stable SecretRef-backed proof key and tenant-native mailer are explicit
    # dependencies. Without them, leave these topics in the durable outbox.
    service = context.get("approval_service")
    queues: dict[str, Literal["scheduler", "agent"]] = {}
    if isinstance(context.get("approval_execution_service"), ApprovalExecutionService):
        queues.update(
            dict.fromkeys(
                ("approvals.execute", "approvals.result", "approvals.result.held"),
                "agent",
            )
        )
    if not isinstance(service, ApprovalService):
        return queues

    async def process(envelope: JobEnvelope) -> None:
        actor = TenantContext(
            envelope.tenant_id, envelope.job_id, "system", envelope.job_id
        )
        if envelope.kind == "approvals.notify":
            await service.send_notices(context=actor, request_id=envelope.aggregate_id)
        elif envelope.kind == "approvals.expire":
            await service.expire(context=actor, request_id=envelope.aggregate_id)
        else:
            raise ValueError("invalid_approval_job")

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    kinds = ("approvals.notify", "approvals.expire")
    handlers.update(dict.fromkeys(kinds, process))
    queues.update(dict.fromkeys(kinds, "scheduler"))
    return queues
