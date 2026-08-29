from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.identity.models import IdentityAssessment
from agents_factory.modules.identity.repository import IdentityRepository
from agents_factory.modules.identity.service import IdentityService


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/identity",
    tags=["platform-admin-identity"],
)


@router.get("/{customer_ref}", response_model=IdentityAssessment)
async def assess_identity(
    tenant_id: UUID,
    customer_ref: str,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> IdentityAssessment:
    context = _context(request, principal, tenant_id)
    return await IdentityService(
        context=context,
        store=IdentityRepository(session, context),
    ).assess(customer_ref)


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )
