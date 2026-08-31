from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import AwareDatetime, Field

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.modules.usage.aggregates import Dimension, UsageSummary, summarize
from agents_factory.modules.usage.models import UsageConfiguration, UsageModel
from agents_factory.modules.usage.recorder import UsageConflict, UsageRecorder


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/usage", tags=["platform-admin-usage"]
)


class ConfigurationView(UsageModel):
    configuration: UsageConfiguration
    revision: int = Field(ge=0)


class ConfigureUsage(UsageModel):
    configuration: UsageConfiguration
    expected_revision: int = Field(ge=0)


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id, principal.user_id, "platform_admin", request.state.correlation_id
    )


def _service(request: Request) -> UsageRecorder:
    service = getattr(request.app.state, "usage_recorder", None)
    if not isinstance(service, UsageRecorder):
        raise HTTPException(status_code=503, detail="usage_service_unavailable")
    return service


@router.get("/configuration")
async def configuration(
    tenant_id: UUID, request: Request, principal: PlatformAdmin
) -> ConfigurationView:
    config, revision = await _service(request).configuration(
        _context(request, principal, tenant_id)
    )
    return ConfigurationView(configuration=config, revision=revision)


@router.put("/configuration")
async def configure(
    tenant_id: UUID, payload: ConfigureUsage, request: Request, principal: PlatformAdmin
) -> ConfigurationView:
    try:
        revision = await _service(request).configure(
            context=_context(request, principal, tenant_id),
            configuration=payload.configuration,
            expected_revision=payload.expected_revision,
        )
    except UsageConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ConfigurationView(configuration=payload.configuration, revision=revision)


@router.get("/summary")
async def summary(
    tenant_id: UUID,
    start: AwareDatetime,
    end: AwareDatetime,
    request: Request,
    principal: PlatformAdmin,
    dimension: Dimension = "tenant",
    resolved_only: bool = False,
) -> UsageSummary:
    try:
        return await summarize(
            _service(request),
            context=_context(request, principal, tenant_id),
            start=start,
            end=end,
            dimension=dimension,
            resolved_only=resolved_only,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="invalid_usage_summary_range"
        ) from exc
