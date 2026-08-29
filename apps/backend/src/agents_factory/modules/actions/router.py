from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.actions.models import ActionRecord
from agents_factory.modules.actions.repository import ActionRepository


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/actions",
    tags=["platform-admin-actions"],
)


@router.get("/{action_id}", response_model=ActionRecord)
async def read_action(
    tenant_id: UUID,
    action_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> ActionRecord:
    context = TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )
    action = await ActionRepository(session, context).get(action_id)
    if action is None:
        raise DomainError(
            type="https://agents-factory.dev/problems/action-not-found",
            title="Action Not Found",
            status=404,
            detail="The requested action does not exist.",
            code="action_not_found",
        )
    return action
