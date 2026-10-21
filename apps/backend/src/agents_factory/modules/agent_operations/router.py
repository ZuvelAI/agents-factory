from uuid import UUID, uuid4

from fastapi import APIRouter

from agents_factory.common.context import TenantContext
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession

from .models import AgentOperationState, OperationRequest
from .service import AgentOperationService

router = APIRouter(
    prefix="/admin/agent-workspace/companies/{tenant_id}/agents/{agent_id}",
    tags=["agent-operations"],
)


@router.get("/operation", response_model=AgentOperationState)
async def get_operation(
    tenant_id: UUID,
    agent_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentOperationState:
    context = TenantContext(tenant_id, principal.user_id, "platform_admin", uuid4())
    return await AgentOperationService(session, context).get_state(agent_id)


@router.post("/operation", response_model=AgentOperationState)
async def set_operation(
    tenant_id: UUID,
    agent_id: UUID,
    request: OperationRequest,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentOperationState:
    context = TenantContext(tenant_id, principal.user_id, "platform_admin", uuid4())
    return await AgentOperationService(session, context).transition(
        agent_id=agent_id,
        enabled=request.enabled,
        expected_revision=request.expected_revision,
    )
