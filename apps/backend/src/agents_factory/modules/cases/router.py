from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.modules.cases.claims_contracts import ClaimCaseConflict
from agents_factory.modules.cases.models import (
    CaseEvent,
    CaseRecord,
    CaseTransition,
    CustomerCaseStatus,
    CustomerResponse,
)
from agents_factory.modules.cases.service import CaseService


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/cases", tags=["platform-admin-cases"]
)


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id, principal.user_id, "platform_admin", request.state.correlation_id
    )


def _service(request: Request) -> CaseService:
    service = getattr(request.app.state, "case_service", None)
    if not isinstance(service, CaseService):
        raise HTTPException(status_code=503, detail="case_service_unavailable")
    return service


@router.get("/{case_id}")
async def status(
    tenant_id: UUID,
    case_id: UUID,
    customer_ref: str,
    request: Request,
    principal: PlatformAdmin,
) -> CustomerCaseStatus:
    result = await _service(request).status(
        context=_context(request, principal, tenant_id),
        customer_ref=customer_ref,
        case_id=case_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="case_unavailable")
    return result


@router.get("/{case_id}/events")
async def history(
    tenant_id: UUID,
    case_id: UUID,
    customer_ref: str,
    request: Request,
    principal: PlatformAdmin,
) -> tuple[CaseEvent, ...]:
    try:
        return await _service(request).history(
            context=_context(request, principal, tenant_id),
            customer_ref=customer_ref,
            case_id=case_id,
        )
    except ClaimCaseConflict:
        raise HTTPException(status_code=404, detail="case_unavailable") from None


@router.post("/{case_id}/transitions")
async def transition(
    tenant_id: UUID,
    case_id: UUID,
    customer_ref: str,
    command: CaseTransition,
    request: Request,
    principal: PlatformAdmin,
) -> CaseRecord:
    try:
        return await _service(request).transition(
            context=_context(request, principal, tenant_id),
            customer_ref=customer_ref,
            case_id=case_id,
            command=command,
        )
    except ClaimCaseConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.post("/{case_id}/customer-responses")
async def customer_response(
    tenant_id: UUID,
    case_id: UUID,
    customer_ref: str,
    command: CustomerResponse,
    request: Request,
    principal: PlatformAdmin,
) -> CaseRecord:
    try:
        return await _service(request).record_customer_response(
            context=_context(request, principal, tenant_id),
            customer_ref=customer_ref,
            case_id=case_id,
            operation_id=command.operation_id,
            issue_persists=command.issue_persists,
            reason=command.reason,
        )
    except ClaimCaseConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
