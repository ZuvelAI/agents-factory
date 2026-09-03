from datetime import datetime

from agents_factory.common.audit import AuditService
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.actions.models import ActionRecord
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.approvals.models import ApprovalRequest, ApprovalState
from agents_factory.modules.approvals.repository import ApprovalRepository
from agents_factory.modules.approvals.result_schema import DecisionResult
from sqlalchemy import text


async def close_request(
    repo: ApprovalRepository,
    request: ApprovalRequest,
    action: ActionRecord,
    state: ApprovalState,
    now: datetime,
) -> None:
    """Shared decision/expiry transaction; no proof key, email or provider needed."""
    await repo.session.execute(
        text(
            "UPDATE public.approval_requests SET state=:state,closed_at=:now WHERE tenant_id=:tenant AND id=:id AND state='PENDING'"
        ),
        {"state": state, "now": now, "tenant": request.tenant_id, "id": request.id},
    )
    await repo.session.execute(
        text(
            "UPDATE public.approval_links SET invalidated_at=:now,otp_digest=NULL WHERE tenant_id=:tenant AND request_id=:request"
        ),
        {"now": now, "tenant": request.tenant_id, "request": request.id},
    )
    if state in {"REJECTED", "EXPIRED"} and action.state == "AWAITING_APPROVAL":
        result = DecisionResult.for_reason(
            "reviewer_rejected" if state == "REJECTED" else "approval_expired"
        )
        await ActionRepository(repo.session, repo.context).finish(
            action=action,
            target="REJECTED" if state == "REJECTED" else "EXPIRED",
            result_payload={
                "approval_request_id": str(request.id),
                "decision_result": result.model_dump(mode="json"),
            },
            finished_at=now,
        )
        await OutboxService(repo.session).enqueue(
            context=repo.context,
            idempotency_key=f"approvals.result:{action.id}",
            topic="approvals.result",
            payload={
                "aggregate_id": str(action.id),
                "approval_request_id": str(request.id),
            },
        )
    await AuditService(repo.session).record(
        context=repo.context,
        event_type=f"approval.{state.lower()}",
        entity_type="approval_request",
        entity_id=request.id,
        payload={"state": state},
    )
