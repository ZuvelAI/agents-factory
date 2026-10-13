from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from agents_factory.common.context import TenantContext
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.agent_factory.models import AgentSpecVersion
from agents_factory.modules.agent_factory.publication_service import (
    PanelPublicationService,
    PublicationState,
)

router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/agent-publication",
    tags=["platform-admin-agent-publication"],
)


class PrepareCandidateRequest(BaseModel):
    expected_revision: int = Field(ge=1)


def service(
    request: Request, tenant_id: UUID, principal, session
) -> PanelPublicationService:
    return PanelPublicationService(
        session,
        TenantContext(
            tenant_id=tenant_id,
            actor_id=principal.user_id,
            actor_type="platform_admin",
            correlation_id=request.state.correlation_id,
        ),
        code_digest=request.app.state.settings.agent_publication_code_digest,
    )


@router.get("", response_model=PublicationState)
async def publication_state(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
):
    return await service(request, tenant_id, principal, session).read_state()


@router.post("/candidates", response_model=AgentSpecVersion)
async def prepare_candidate(
    tenant_id: UUID,
    payload: PrepareCandidateRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
):
    return await service(request, tenant_id, principal, session).prepare_candidate(
        expected_revision=payload.expected_revision
    )
