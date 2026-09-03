from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import text

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.common.security import PlatformAdmin
from agents_factory.database import set_tenant_context
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.privacy.models import PrivacyJob, PrivacyJobRequest


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/privacy", tags=["platform-admin-privacy"]
)


@router.post("/jobs", response_model=PrivacyJob, status_code=status.HTTP_202_ACCEPTED)
async def request_privacy_job(
    tenant_id: UUID,
    payload: PrivacyJobRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> PrivacyJob:
    context = TenantContext(
        tenant_id, principal.user_id, "platform_admin", request.state.correlation_id
    )
    await set_tenant_context(session, tenant_id)
    job_id = new_uuid7()
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO public.privacy_jobs (id,tenant_id,operation,subject_type,"
                    "subject_ref,legal_hold,idempotency_key,requested_by_admin_id) VALUES "
                    "(:id,:tenant,:operation,:subject_type,:subject_ref,:hold,:key,:admin) "
                    "ON CONFLICT (tenant_id,idempotency_key) DO UPDATE SET "
                    "idempotency_key=excluded.idempotency_key RETURNING id,operation,"
                    "subject_type,subject_ref,status,legal_hold,result_manifest,error_code,"
                    "requested_at,started_at,completed_at"
                ),
                {
                    "id": job_id,
                    "tenant": tenant_id,
                    "operation": payload.operation,
                    "subject_type": payload.subject_type,
                    "subject_ref": payload.subject_ref,
                    "hold": payload.legal_hold,
                    "key": payload.idempotency_key,
                    "admin": principal.user_id,
                },
            )
        )
        .mappings()
        .one()
    )
    resolved_id = row["id"]
    await OutboxService(session).enqueue(
        context=context,
        idempotency_key=f"privacy.process:{resolved_id}",
        topic="privacy.process",
        payload={"aggregate_id": str(resolved_id)},
    )
    await AuditService(session).record(
        context=context,
        event_type="privacy.job.requested",
        entity_type="privacy_job",
        entity_id=resolved_id,
        payload={
            "operation": payload.operation,
            "subject_type": payload.subject_type,
            "legal_hold": payload.legal_hold,
        },
    )
    return PrivacyJob.model_validate(dict(row))


@router.get("/jobs", response_model=tuple[PrivacyJob, ...])
async def list_privacy_jobs(
    tenant_id: UUID, _principal: PlatformAdmin, session: TransactionSession
) -> tuple[PrivacyJob, ...]:
    await set_tenant_context(session, tenant_id)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,operation,subject_type,subject_ref,status,legal_hold,"
                    "result_manifest,error_code,requested_at,started_at,completed_at FROM "
                    "public.privacy_jobs WHERE tenant_id=:tenant ORDER BY requested_at DESC,id DESC LIMIT 100"
                ),
                {"tenant": tenant_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(PrivacyJob.model_validate(dict(row)) for row in rows)
