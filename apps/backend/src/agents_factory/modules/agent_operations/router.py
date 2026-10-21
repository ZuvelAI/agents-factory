from uuid import UUID, uuid4

from fastapi import APIRouter, Request

from agents_factory.common.context import TenantContext
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession

from .models import AgentOperationView, OperationRequest
from .service import AgentOperationService
from agents_factory.modules.agent_factory.publication_service import publication_problem


def controls_available(request: Request) -> bool:
    return getattr(request.app.state, "agent_operation_controls_enabled", False) is True


router = APIRouter(
    prefix="/admin/agent-workspace/companies/{tenant_id}/agents/{agent_id}",
    tags=["agent-operations"],
)


@router.get("/operation", response_model=AgentOperationView)
async def get_operation(
    tenant_id: UUID,
    agent_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
    request: Request,
) -> AgentOperationView:
    context = TenantContext(tenant_id, principal.user_id, "platform_admin", uuid4())
    state = await AgentOperationService(session, context).get_state(agent_id)
    return AgentOperationView(
        **state.model_dump(), controls_available=controls_available(request)
    )


@router.post("/operation", response_model=AgentOperationView)
async def set_operation(
    tenant_id: UUID,
    agent_id: UUID,
    request: OperationRequest,
    principal: PlatformAdmin,
    session: TransactionSession,
    http: Request,
) -> AgentOperationView:
    if not controls_available(http):
        raise publication_problem(
            "agent_operation_controls_unavailable",
            "El control operativo todavía no está habilitado.",
            503,
        )
    context = TenantContext(tenant_id, principal.user_id, "platform_admin", uuid4())
    state = await AgentOperationService(session, context).transition(
        agent_id=agent_id,
        enabled=request.enabled,
        expected_revision=request.expected_revision,
    )
    return AgentOperationView(**state.model_dump(), controls_available=True)
