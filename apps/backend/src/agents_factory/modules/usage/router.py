from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import AwareDatetime, Field
from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.modules.usage.aggregates import (
    Dimension,
    MarginEstimate,
    UsageSummary,
    estimate_margin,
    summarize,
)
from agents_factory.modules.usage.models import Money, UsageConfiguration, UsageModel
from agents_factory.modules.usage.recorder import UsageConflict, UsageRecorder
from agents_factory.modules.usage.alerts import UsageAlertPage, list_alerts


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/usage", tags=["platform-admin-usage"]
)


class ConfigurationView(UsageModel):
    configuration: UsageConfiguration
    revision: int = Field(ge=0)


class ConfigureUsage(UsageModel):
    configuration: UsageConfiguration
    expected_revision: int = Field(ge=0)


class UsageFreshness(UsageModel):
    generated_at: datetime
    latest_recorded_at: datetime | None
    records: int = Field(ge=0)
    state: Literal["fresh", "stale", "empty"]


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


@router.get("/alerts")
async def alerts(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    before: UUID | None = None,
    limit: int = 100,
) -> UsageAlertPage:
    try:
        async with _service(request).transaction(
            _context(request, principal, tenant_id)
        ) as session:
            return await list_alerts(session, before=before, limit=limit)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_alert_query") from None


@router.get("/freshness")
async def freshness(
    tenant_id: UUID, request: Request, principal: PlatformAdmin
) -> UsageFreshness:
    generated_at = datetime.now(UTC)
    async with _service(request).transaction(
        _context(request, principal, tenant_id)
    ) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT count(*) AS records,max(recorded_at) AS latest "
                        "FROM public.usage_records WHERE tenant_id=:tenant"
                    ),
                    {"tenant": tenant_id},
                )
            )
            .mappings()
            .one()
        )
    latest = row["latest"]
    return UsageFreshness(
        generated_at=generated_at,
        latest_recorded_at=latest,
        records=row["records"],
        state=(
            "empty"
            if latest is None
            else "fresh"
            if (generated_at - latest).total_seconds() <= 86_400
            else "stale"
        ),
    )


@router.get("/margin")
async def margin(
    tenant_id: UUID,
    start: AwareDatetime,
    end: AwareDatetime,
    revenue_amount: Decimal,
    currency: str,
    request: Request,
    principal: PlatformAdmin,
) -> MarginEstimate:
    try:
        report = await summarize(
            _service(request),
            context=_context(request, principal, tenant_id),
            start=start,
            end=end,
            dimension="tenant",
        )
        if report.has_more:
            raise ValueError("incomplete_margin_report")
        return estimate_margin(
            Money(amount=revenue_amount, currency=currency), report.groups
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_margin_report") from exc
