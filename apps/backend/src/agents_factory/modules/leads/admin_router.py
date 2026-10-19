from uuid import UUID
from fastapi import APIRouter, Query
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from .read_models import (
    ProspectDetail,
    ProspectEventPage,
    ProspectPage,
    ProspectSummary,
)
from .read_repository import LeadReadRepository

router = APIRouter(
    prefix="/admin/agent-workspace/companies/{tenant_id}",
    tags=["platform-admin-prospects"],
)


@router.get("/prospects", response_model=ProspectPage)
async def prospects(
    tenant_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
    agent_id: UUID | None = None,
    q: str | None = Query(None, max_length=200),
    cursor: str | None = Query(None, max_length=512),
    limit: int = Query(20, ge=1, le=20),
) -> ProspectPage:
    return await LeadReadRepository(session).list(
        tenant_id, agent=agent_id, q=q, cursor=cursor, limit=limit
    )


@router.get("/prospects/{prospect_id}", response_model=ProspectDetail)
async def prospect(
    tenant_id: UUID,
    prospect_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
    agent_id: UUID | None = None,
) -> ProspectDetail:
    return await LeadReadRepository(session).detail(tenant_id, prospect_id, agent_id)


@router.get("/prospects/{prospect_id}/events", response_model=ProspectEventPage)
async def events(
    tenant_id: UUID,
    prospect_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
    cursor: str | None = Query(None, max_length=512),
    limit: int = Query(20, ge=1, le=20),
) -> ProspectEventPage:
    return await LeadReadRepository(session).events(
        tenant_id, prospect_id, cursor=cursor, limit=limit
    )


@router.get(
    "/conversations/{conversation_id}/prospect", response_model=ProspectSummary | None
)
async def conversation_prospect(
    tenant_id: UUID,
    conversation_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> ProspectSummary | None:
    return await LeadReadRepository(session).for_conversation(
        tenant_id, conversation_id
    )
