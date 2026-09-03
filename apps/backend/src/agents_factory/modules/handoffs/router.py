from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.modules.handoffs.models import (
    HandoffConfiguration,
    HandoffConfigurationRecord,
    HandoffReason,
    HandoffRecord,
    HumanSurfaceOption,
    Model,
)
from agents_factory.modules.handoffs.service import HandoffService

router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/handoffs", tags=["platform-admin-handoffs"]
)


class ConfigureInput(Model):
    configuration: HandoffConfiguration
    expected_revision: int = Field(default=0, ge=0)


class RequestInput(Model):
    reason: HandoffReason


def _service(request: Request) -> HandoffService:
    service = getattr(request.app.state, "handoff_service", None)
    if not isinstance(service, HandoffService):
        raise HTTPException(status_code=503, detail="handoff_service_unavailable")
    return service


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id, principal.user_id, "platform_admin", request.state.correlation_id
    )


@router.get("/configurations", response_model=tuple[HandoffConfigurationRecord, ...])
async def configurations(
    tenant_id: UUID, request: Request, principal: PlatformAdmin
) -> tuple[HandoffConfigurationRecord, ...]:
    return await _service(request).configurations(
        context=_context(request, principal, tenant_id)
    )


@router.get("/surfaces", response_model=tuple[HumanSurfaceOption, ...])
async def surfaces(
    tenant_id: UUID, request: Request, principal: PlatformAdmin
) -> tuple[HumanSurfaceOption, ...]:
    return _service(request).surface_options(
        context=_context(request, principal, tenant_id)
    )


@router.put("/accounts/{account_id}")
async def configure(
    tenant_id: UUID,
    account_id: UUID,
    body: ConfigureInput,
    request: Request,
    principal: PlatformAdmin,
) -> dict[str, int]:
    revision = await _service(request).configure(
        context=_context(request, principal, tenant_id),
        account_id=account_id,
        configuration=body.configuration,
        expected_revision=body.expected_revision,
    )
    return {"revision": revision}


@router.post("/conversations/{conversation_id}")
async def request_handoff(
    tenant_id: UUID,
    conversation_id: UUID,
    body: RequestInput,
    request: Request,
    principal: PlatformAdmin,
) -> HandoffRecord:
    return await _service(request).request(
        context=_context(request, principal, tenant_id),
        conversation_id=conversation_id,
        reason=body.reason,
    )


@router.get("/{handoff_id}")
async def status(
    tenant_id: UUID, handoff_id: UUID, request: Request, principal: PlatformAdmin
) -> HandoffRecord:
    return await _service(request).status(
        context=_context(request, principal, tenant_id), handoff_id=handoff_id
    )
