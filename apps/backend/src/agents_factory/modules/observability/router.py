from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.observability.health import HealthService
from agents_factory.modules.observability.incidents import IncidentService
from agents_factory.modules.observability.models import (
    HealthSnapshot,
    IncidentRecord,
    TraceReconstruction,
)
from agents_factory.modules.observability.tracing import TraceReconstructor


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/observability",
    tags=["platform-admin-observability"],
)


@router.get("/traces/{correlation_id}", response_model=TraceReconstruction)
async def reconstruct_trace(
    tenant_id: UUID,
    correlation_id: UUID,
    _principal: PlatformAdmin,
    session: TransactionSession,
) -> TraceReconstruction:
    return await TraceReconstructor(session).reconstruct(
        tenant_id=tenant_id, correlation_id=correlation_id
    )


@router.get("/health", response_model=HealthSnapshot)
async def tenant_health(
    tenant_id: UUID,
    _principal: PlatformAdmin,
    session: TransactionSession,
) -> HealthSnapshot:
    return await HealthService(session).snapshot(tenant_id=tenant_id)


@router.get("/incidents", response_model=tuple[IncidentRecord, ...])
async def incidents(
    tenant_id: UUID,
    _principal: PlatformAdmin,
    session: TransactionSession,
) -> tuple[IncidentRecord, ...]:
    return await IncidentService(session).list_open(tenant_id=tenant_id)
