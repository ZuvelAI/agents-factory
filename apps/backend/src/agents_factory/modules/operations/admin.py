from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.database import set_tenant_context
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.cases.models import CaseRecord, CaseTransition
from agents_factory.modules.cases.service import CaseService
from agents_factory.modules.observability.health import HealthService
from agents_factory.modules.observability.incidents import IncidentService
from agents_factory.modules.observability.models import HealthSnapshot, IncidentRecord
from agents_factory.modules.evals.models import QualityGateOverview
from agents_factory.modules.evals.quality_gate import quality_gate_overview


CasePriority = Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]
DlqAction = Literal["RETRY", "DISCARD", "RESOLVE"]
OperationalState = Literal["HEALTHY", "ACTIVE", "IDLE", "DEGRADED", "UNKNOWN"]


class OperationalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UnavailableFeature(OperationalModel):
    available: Literal[False] = False
    code: str
    reason: str
    owner_task: int = Field(ge=44, le=47)


class QueueTopic(OperationalModel):
    topic: str
    pending: int = Field(ge=0)
    processing: int = Field(ge=0)
    failed: int = Field(ge=0)
    dead_letter: int = Field(ge=0)
    oldest_pending_at: datetime | None
    state: OperationalState
    state_basis: Literal["RECORDED_QUEUE_STATE"] = "RECORDED_QUEUE_STATE"


class IntegrationOperation(OperationalModel):
    id: UUID
    connector_name: str
    connection_status: str
    health_status: str
    last_health_checked_at: datetime | None
    last_error_code: str | None


class DeadLetterItem(OperationalModel):
    id: UUID
    outbox_job_id: UUID
    topic: str
    reason_code: str
    status: Literal["open", "resolved", "discarded"]
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class OperationalAudit(OperationalModel):
    event_type: str
    entity_id: UUID | None
    correlation_id: UUID
    occurred_at: datetime


class DeploymentRecord(OperationalModel):
    id: UUID
    environment: Literal["STAGING", "PRODUCTION"]
    release_version: str
    backend_image_digest: str
    control_plane_image_digest: str
    migration_version: str
    status: Literal[
        "PENDING", "MIGRATING", "PROMOTING", "HEALTHY", "FAILED", "ROLLED_BACK"
    ]
    quality_gate_decision_id: UUID
    correlation_id: UUID
    started_at: datetime
    completed_at: datetime | None


class DeploymentOverview(OperationalModel):
    available: Literal[True] = True
    promotion_mode: Literal["GITHUB_ENVIRONMENT_APPROVAL"] = (
        "GITHUB_ENVIRONMENT_APPROVAL"
    )
    latest: tuple[DeploymentRecord, ...]


class OperationsWorkspace(OperationalModel):
    generated_at: datetime
    state: OperationalState
    topics: tuple[QueueTopic, ...]
    integrations: tuple[IntegrationOperation, ...]
    dead_letters: tuple[DeadLetterItem, ...]
    dead_letter_page: int = Field(ge=1)
    dead_letter_has_more: bool
    recent_audit: tuple[OperationalAudit, ...]
    health: HealthSnapshot
    incidents: tuple[IncidentRecord, ...]
    quality_gate: QualityGateOverview
    deployments: DeploymentOverview


class CaseSummary(OperationalModel):
    id: UUID
    capability: str
    issue_type: str
    revision: int = Field(ge=1)
    status: str
    priority: CasePriority
    target_status: str
    target_at: datetime
    reviewer_reference: str
    approval_status: str
    latest_event: str | None
    latest_reason: str | None
    updated_at: datetime


class CaseWorkspace(OperationalModel):
    generated_at: datetime
    cases: tuple[CaseSummary, ...]
    page: int = Field(ge=1)
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    has_more: bool


class DlqMutationRequest(OperationalModel):
    action: DlqAction
    expected_status: Literal["open"] = "open"
    confirmation: Literal[True]
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def trimmed_reason(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("reason must be trimmed")
        return value


class ResolveCaseRequest(OperationalModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1_000)
    customer_result: str = Field(min_length=1, max_length=4_000)

    @field_validator("reason", "customer_result")
    @classmethod
    def trimmed_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("value must be trimmed")
        return value


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}", tags=["platform-admin-operations"]
)


@router.get("/operations/workspace", response_model=OperationsWorkspace)
async def operations_workspace(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
    page: int = 1,
    limit: int = 50,
) -> OperationsWorkspace:
    if not 1 <= page or not 1 <= limit <= 100:
        raise _operations_error("invalid_operations_page", status=422)
    return await OperationsAdminService(
        session, _context(request, principal, tenant_id)
    ).workspace(page=page, limit=limit)


@router.post(
    "/operations/dead-letters/{dead_letter_id}/actions",
    response_model=DeadLetterItem,
)
async def mutate_dead_letter(
    tenant_id: UUID,
    dead_letter_id: UUID,
    payload: DlqMutationRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> DeadLetterItem:
    return await OperationsAdminService(
        session, _context(request, principal, tenant_id)
    ).mutate_dead_letter(dead_letter_id, payload)


@router.get("/case-workspace", response_model=CaseWorkspace)
async def case_workspace(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
    priority: CasePriority | None = None,
    overdue: bool = False,
    page: int = 1,
    limit: int = 50,
) -> CaseWorkspace:
    if not 1 <= page or not 1 <= limit <= 100:
        raise _operations_error("invalid_case_page", status=422)
    return await OperationsAdminService(
        session, _context(request, principal, tenant_id)
    ).cases(priority=priority, overdue=overdue, page=page, limit=limit)


@router.post("/cases/{case_id}/resolve", response_model=CaseRecord)
async def resolve_case(
    tenant_id: UUID,
    case_id: UUID,
    payload: ResolveCaseRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> CaseRecord:
    context = _context(request, principal, tenant_id)
    await set_tenant_context(session, tenant_id)
    customer_ref = await session.scalar(
        text(
            "SELECT customer_ref FROM public.cases WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": tenant_id, "id": case_id},
    )
    if not isinstance(customer_ref, str):
        raise _operations_error("case_not_found", status=404)
    service = getattr(request.app.state, "case_service", None)
    if not isinstance(service, CaseService):
        raise _operations_error("case_service_unavailable", status=503)
    return await service.transition(
        context=context,
        customer_ref=customer_ref,
        case_id=case_id,
        command=CaseTransition(
            operation_id=new_uuid7(),
            expected_revision=payload.expected_revision,
            target="RESOLVED",
            reason=payload.reason,
            customer_result=payload.customer_result,
        ),
    )


class OperationsAdminService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def workspace(self, *, page: int, limit: int) -> OperationsWorkspace:
        await set_tenant_context(self._session, self._context.tenant_id)
        topic_rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT topic,count(*) FILTER(WHERE status IN "
                        "('pending','dispatching','queued')) AS pending,"
                        "count(*) FILTER(WHERE status='processing') AS processing,"
                        "count(*) FILTER(WHERE status='failed') AS failed,"
                        "count(*) FILTER(WHERE status='dead_letter') AS dead_letter,"
                        "min(available_at) FILTER(WHERE status IN "
                        "('pending','dispatching','queued')) AS oldest_pending_at "
                        "FROM public.outbox_jobs WHERE tenant_id=:tenant GROUP BY topic "
                        "ORDER BY topic"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        topics = tuple(_queue_topic(row) for row in topic_rows)
        integrations = await self._integrations()
        dead_letters, has_more = await self._dead_letters(page=page, limit=limit)
        audits = await self._audits()
        health = await HealthService(self._session).snapshot(
            tenant_id=self._context.tenant_id
        )
        incidents = await IncidentService(self._session).list_open(
            tenant_id=self._context.tenant_id
        )
        quality_gate = await quality_gate_overview(
            self._session, tenant_id=self._context.tenant_id
        )
        deployments = await self._deployments()
        return OperationsWorkspace(
            generated_at=datetime.now(UTC),
            state=(
                "DEGRADED"
                if any(item.state == "DEGRADED" for item in topics)
                or any(
                    item.health_status in {"ERROR", "REAUTH_REQUIRED"}
                    for item in integrations
                )
                else "ACTIVE"
                if any(item.state == "ACTIVE" for item in topics)
                else "IDLE"
            ),
            topics=topics,
            integrations=integrations,
            dead_letters=dead_letters,
            dead_letter_page=page,
            dead_letter_has_more=has_more,
            recent_audit=audits,
            health=health,
            incidents=incidents,
            quality_gate=quality_gate,
            deployments=deployments,
        )

    async def cases(
        self,
        *,
        priority: CasePriority | None,
        overdue: bool,
        page: int,
        limit: int,
    ) -> CaseWorkspace:
        await set_tenant_context(self._session, self._context.tenant_id)
        offset = (page - 1) * limit
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT case_record.id,case_record.capability,"
                        "case_record.issue_type,case_record.revision,case_record.status,"
                        "case_record.priority,CASE WHEN case_record.target_at<=now() "
                        "AND case_record.status NOT IN ('RESOLVED','CLOSED','REJECTED',"
                        "'CANCELLED','EXPIRED','DUPLICATE') THEN 'OVERDUE' "
                        "ELSE case_record.target_status END AS target_status,"
                        "case_record.target_at,case_record.updated_at,event.actor_id,"
                        "event.event_type,event.reason,coalesce(approval.state,CASE WHEN "
                        "case_record.status='PENDING_APPROVAL' THEN 'PENDING' ELSE "
                        "'NOT_REQUIRED' END) AS approval_status,count(*) OVER() AS total "
                        "FROM public.cases AS case_record LEFT JOIN LATERAL (SELECT "
                        "case_event.actor_id,case_event.event_type,case_event.reason,"
                        "case_event.action_reference FROM public.case_events AS case_event "
                        "WHERE case_event.tenant_id=case_record.tenant_id AND "
                        "case_event.case_id=case_record.id ORDER BY case_event.created_at "
                        "DESC,case_event.id DESC LIMIT 1) AS event ON true LEFT JOIN LATERAL "
                        "(SELECT approval_request.state FROM public.approval_requests AS "
                        "approval_request WHERE approval_request.tenant_id=case_record.tenant_id "
                        "AND approval_request.action_id=event.action_reference ORDER BY "
                        "approval_request.created_at DESC,approval_request.id DESC LIMIT 1) "
                        "AS approval ON true WHERE case_record.tenant_id=:tenant AND "
                        "(:priority IS NULL OR case_record.priority=:priority) AND "
                        "(NOT :overdue OR (case_record.target_at<=now() AND "
                        "case_record.status NOT IN ('RESOLVED','CLOSED','REJECTED',"
                        "'CANCELLED','EXPIRED','DUPLICATE'))) ORDER BY "
                        "case_record.target_at,case_record.id LIMIT :limit OFFSET :offset"
                    ),
                    {
                        "tenant": self._context.tenant_id,
                        "priority": priority,
                        "overdue": overdue,
                        "limit": limit,
                        "offset": offset,
                    },
                )
            )
            .mappings()
            .all()
        )
        total = 0 if not rows else cast(int, rows[0]["total"])
        return CaseWorkspace(
            generated_at=datetime.now(UTC),
            cases=tuple(_case_summary(row) for row in rows),
            page=page,
            limit=limit,
            total=total,
            has_more=offset + len(rows) < total,
        )

    async def mutate_dead_letter(
        self, dead_letter_id: UUID, payload: DlqMutationRequest
    ) -> DeadLetterItem:
        await set_tenant_context(self._session, self._context.tenant_id)
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT dlq.id,dlq.outbox_job_id,dlq.status,job.status AS "
                        "job_status FROM public.dead_letter_jobs AS dlq JOIN "
                        "public.outbox_jobs AS job ON job.tenant_id=dlq.tenant_id AND "
                        "job.id=dlq.outbox_job_id WHERE dlq.tenant_id=:tenant AND "
                        "dlq.id=:id FOR UPDATE OF dlq,job"
                    ),
                    {"tenant": self._context.tenant_id, "id": dead_letter_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _operations_error("dead_letter_not_found", status=404)
        if row["status"] != payload.expected_status:
            raise _operations_error("dead_letter_changed")
        next_status = "resolved" if payload.action != "DISCARD" else "discarded"
        if payload.action == "RETRY":
            if row["job_status"] != "dead_letter":
                raise _operations_error("dead_letter_job_changed")
            await self._session.execute(
                text(
                    "UPDATE public.outbox_jobs SET status='pending',available_at=now(),"
                    "dispatch_lease_id=NULL,dispatch_lease_expires_at=NULL,"
                    "dispatched_at=NULL,last_error_code=NULL,completed_at=NULL,"
                    "max_attempts=greatest(max_attempts,attempt_count+1),updated_at=now() "
                    "WHERE tenant_id=:tenant AND id=:job AND status='dead_letter'"
                ),
                {
                    "tenant": self._context.tenant_id,
                    "job": row["outbox_job_id"],
                },
            )
        updated = (
            await self._session.execute(
                text(
                    "UPDATE public.dead_letter_jobs SET status=:status,updated_at=now() "
                    "WHERE tenant_id=:tenant AND id=:id AND status='open' RETURNING id"
                ),
                {
                    "status": next_status,
                    "tenant": self._context.tenant_id,
                    "id": dead_letter_id,
                },
            )
        ).scalar_one_or_none()
        if updated is None:
            raise _operations_error("dead_letter_changed")
        await AuditService(self._session).record(
            context=self._context,
            event_type=f"job.dead_letter.{payload.action.lower()}",
            entity_type="dead_letter_job",
            entity_id=dead_letter_id,
            payload={
                "reason": payload.reason,
                "outbox_job_id": str(row["outbox_job_id"]),
            },
        )
        item = await self._dead_letter(dead_letter_id)
        assert item is not None
        return item

    async def _integrations(self) -> tuple[IntegrationOperation, ...]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id,connector_name,status AS connection_status,"
                        "health_status,last_health_checked_at,last_error_code FROM "
                        "public.integration_connections WHERE tenant_id=:tenant AND "
                        "status<>'REVOKED' UNION ALL SELECT id,'meta_whatsapp',status,"
                        "health_status,last_health_checked_at,last_error_code FROM "
                        "public.whatsapp_accounts WHERE tenant_id=:tenant AND "
                        "status<>'revoked' ORDER BY connector_name,id"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(IntegrationOperation.model_validate(dict(row)) for row in rows)

    async def _dead_letters(
        self, *, page: int, limit: int
    ) -> tuple[tuple[DeadLetterItem, ...], bool]:
        rows = (
            (
                await self._session.execute(
                    _DEAD_LETTERS,
                    {
                        "tenant": self._context.tenant_id,
                        "limit": limit + 1,
                        "offset": (page - 1) * limit,
                    },
                )
            )
            .mappings()
            .all()
        )
        return (
            tuple(DeadLetterItem.model_validate(dict(row)) for row in rows[:limit]),
            len(rows) > limit,
        )

    async def _dead_letter(self, dead_letter_id: UUID) -> DeadLetterItem | None:
        row = (
            (
                await self._session.execute(
                    _DEAD_LETTER,
                    {"tenant": self._context.tenant_id, "id": dead_letter_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else DeadLetterItem.model_validate(dict(row))

    async def _audits(self) -> tuple[OperationalAudit, ...]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT event_type,entity_id,correlation_id,occurred_at FROM "
                        "public.audit_events WHERE tenant_id=:tenant AND event_type LIKE "
                        "'job.dead_letter.%' ORDER BY occurred_at DESC LIMIT 50"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(OperationalAudit.model_validate(dict(row)) for row in rows)

    async def _deployments(self) -> DeploymentOverview:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT DISTINCT ON (environment) id,environment,release_version,"
                        "backend_image_digest,control_plane_image_digest,migration_version,"
                        "status,quality_gate_decision_id,correlation_id,started_at,completed_at "
                        "FROM public.deployment_records WHERE tenant_id=:tenant ORDER BY "
                        "environment,started_at DESC,id DESC"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return DeploymentOverview(
            latest=tuple(DeploymentRecord.model_validate(dict(row)) for row in rows)
        )


_DEAD_LETTER_COLUMNS = (
    "dlq.id,dlq.outbox_job_id,job.topic,dlq.reason_code,dlq.status,"
    "job.attempt_count,job.max_attempts,job.last_error_code,dlq.created_at,dlq.updated_at"
)
_DEAD_LETTERS = text(
    f"SELECT {_DEAD_LETTER_COLUMNS} FROM public.dead_letter_jobs AS dlq JOIN "
    "public.outbox_jobs AS job ON job.tenant_id=dlq.tenant_id AND "
    "job.id=dlq.outbox_job_id WHERE dlq.tenant_id=:tenant ORDER BY "
    "dlq.created_at DESC,dlq.id DESC LIMIT :limit OFFSET :offset"
)
_DEAD_LETTER = text(
    f"SELECT {_DEAD_LETTER_COLUMNS} FROM public.dead_letter_jobs AS dlq JOIN "
    "public.outbox_jobs AS job ON job.tenant_id=dlq.tenant_id AND "
    "job.id=dlq.outbox_job_id WHERE dlq.tenant_id=:tenant AND dlq.id=:id"
)


def _queue_topic(row: object) -> QueueTopic:
    values = cast(dict[str, object], row)
    failed = cast(int, values["failed"])
    dead_letter = cast(int, values["dead_letter"])
    pending = cast(int, values["pending"])
    processing = cast(int, values["processing"])
    state: OperationalState = (
        "DEGRADED"
        if failed or dead_letter
        else "ACTIVE"
        if pending or processing
        else "IDLE"
    )
    return QueueTopic(
        topic=str(values["topic"]),
        pending=pending,
        processing=processing,
        failed=failed,
        dead_letter=dead_letter,
        oldest_pending_at=cast(datetime | None, values["oldest_pending_at"]),
        state=state,
    )


def _case_summary(row: object) -> CaseSummary:
    values = cast(dict[str, object], row)
    actor = values["actor_id"]
    reviewer = "Unassigned"
    if isinstance(actor, UUID):
        reviewer = f"Platform admin ••••{str(actor)[-4:]}"
    return CaseSummary(
        id=cast(UUID, values["id"]),
        capability=str(values["capability"]),
        issue_type=str(values["issue_type"]),
        revision=cast(int, values["revision"]),
        status=str(values["status"]),
        priority=cast(CasePriority, values["priority"]),
        target_status=str(values["target_status"]),
        target_at=cast(datetime, values["target_at"]),
        reviewer_reference=reviewer,
        approval_status=str(values["approval_status"]),
        latest_event=None
        if values["event_type"] is None
        else str(values["event_type"]),
        latest_reason=None if values["reason"] is None else str(values["reason"]),
        updated_at=cast(datetime, values["updated_at"]),
    )


def _unavailable(code: str, reason: str, owner_task: int) -> UnavailableFeature:
    return UnavailableFeature(code=code, reason=reason, owner_task=owner_task)


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )


def _operations_error(code: str, *, status: int = 409) -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/control-plane-operations",
        title="Operational Action Unavailable",
        status=status,
        detail="The requested operational action could not be completed.",
        code=code,
    )
