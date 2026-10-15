from uuid import UUID
from fastapi import APIRouter, Query
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from .workspace_models import AgentOverview, AgentPage, CompanyPage
from .workspace_service import AgentWorkspaceService

router = APIRouter(prefix="/admin/agent-workspace", tags=["platform-admin-workspace"])


@router.get("/companies", response_model=CompanyPage)
async def companies(
    principal: PlatformAdmin,
    session: TransactionSession,
    query: str | None = Query(default=None, max_length=200),
    cursor: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
) -> CompanyPage:
    return await AgentWorkspaceService(session, principal).list_companies(
        query=query, cursor=cursor, limit=limit
    )


@router.get("/companies/{tenant_id}/agents", response_model=AgentPage)
async def agents(
    tenant_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
    cursor: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
) -> AgentPage:
    return await AgentWorkspaceService(session, principal).list_agents(
        tenant_id=tenant_id, cursor=cursor, limit=limit
    )


@router.get("/companies/{tenant_id}/agents/{agent_id}", response_model=AgentOverview)
async def agent(
    tenant_id: UUID,
    agent_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentOverview:
    return await AgentWorkspaceService(session, principal).get_agent(
        tenant_id=tenant_id, agent_id=agent_id
    )
