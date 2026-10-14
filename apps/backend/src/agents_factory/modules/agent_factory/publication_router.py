from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.agent_factory.models import AgentSpecVersion
from agents_factory.modules.agent_factory.publication_service import (
    PanelPublicationService,
    PublicationState,
)
from agents_factory.modules.agent_factory.publication_evidence import (
    PublicationEvidenceService,
    PublicationTestRun,
)
from agents_factory.modules.agent_factory.channel_binding import AccountAgentBinding

router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/agent-publication",
    tags=["platform-admin-agent-publication"],
)


class PrepareCandidateRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class ReviewTestsRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    approved: bool


class PublishRequest(BaseModel):
    version_id: UUID
    whatsapp_account_id: UUID
    expected_revision: int = Field(ge=1)
    test_run_id: UUID
    expected_binding_revision: int = Field(ge=0)


class RollbackRequest(BaseModel):
    whatsapp_account_id: UUID
    target_version_id: UUID
    expected_binding_revision: int = Field(ge=1)


def service(
    request: Request, tenant_id: UUID, principal: AdminPrincipal, session: AsyncSession
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
) -> PublicationState:
    return await service(request, tenant_id, principal, session).read_state()


@router.post("/candidates", response_model=AgentSpecVersion)
async def prepare_candidate(
    tenant_id: UUID,
    payload: PrepareCandidateRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    return await service(request, tenant_id, principal, session).prepare_candidate(
        expected_revision=payload.expected_revision
    )


def evidence(
    request: Request, tenant_id: UUID, principal: AdminPrincipal, session: AsyncSession
) -> PublicationEvidenceService:
    operation = service(request, tenant_id, principal, session)
    return PublicationEvidenceService(
        session, operation.context, code_digest=operation.code_digest
    )


@router.post(
    "/candidates/{version_id}/tests", response_model=PublicationTestRun, status_code=202
)
async def request_tests(
    tenant_id: UUID,
    version_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> PublicationTestRun:
    return await evidence(request, tenant_id, principal, session).request_tests(
        version_id
    )


@router.get("/tests/{run_id}", response_model=PublicationTestRun)
async def read_tests(
    tenant_id: UUID,
    run_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> PublicationTestRun:
    return await evidence(request, tenant_id, principal, session).read_run(run_id)


@router.post("/tests/{run_id}/review", response_model=PublicationTestRun)
async def review_tests(
    tenant_id: UUID,
    run_id: UUID,
    payload: ReviewTestsRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> PublicationTestRun:
    return await evidence(request, tenant_id, principal, session).review(
        run_id, approved=payload.approved, expected_revision=payload.expected_revision
    )


@router.post("/publish", response_model=AccountAgentBinding)
async def publish(
    tenant_id: UUID,
    payload: PublishRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AccountAgentBinding:
    return await service(request, tenant_id, principal, session).publish(
        **payload.model_dump()
    )


@router.post("/rollback", response_model=AccountAgentBinding)
async def rollback(
    tenant_id: UUID,
    payload: RollbackRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AccountAgentBinding:
    return await service(request, tenant_id, principal, session).rollback(
        **payload.model_dump()
    )
