from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from agents_factory.common.context import TenantContext
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.evals.models import (
    QualityGateDecision,
    QualityGateOverview,
    QualityGateRunRequest,
)
from agents_factory.modules.evals.quality_gate import quality_gate_overview
from agents_factory.modules.evals.runner import ProductionEvalRunner


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/evals", tags=["platform-admin-evals"]
)


@router.get("/quality-gate", response_model=QualityGateOverview)
async def gate_overview(
    tenant_id: UUID, _principal: PlatformAdmin, session: TransactionSession
) -> QualityGateOverview:
    return await quality_gate_overview(session, tenant_id=tenant_id)


@router.post("/quality-gate/runs", response_model=QualityGateDecision)
async def run_quality_gate(
    tenant_id: UUID,
    payload: QualityGateRunRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> QualityGateDecision:
    return await ProductionEvalRunner(
        session,
        TenantContext(
            tenant_id=tenant_id,
            actor_id=principal.user_id,
            actor_type="platform_admin",
            correlation_id=request.state.correlation_id,
        ),
    ).run(payload)
