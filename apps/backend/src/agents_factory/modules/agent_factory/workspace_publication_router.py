"""Authorized per-agent commands; no SQL, provider calls or secret-bearing errors."""

from typing import Literal
from typing import Any
from collections.abc import Callable, Coroutine
from uuid import UUID
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from agents_factory.common.context import TenantContext
from agents_factory.common.security import PlatformAdmin
from agents_factory.common.errors import DomainError
from agents_factory.dependencies import TransactionSession
from .configuration_errors import SafeConfigurationRoute
from .workspace_publication_models import (
    PrepareWorkspaceRequest,
    PublishWorkspaceRequest,
    RollbackWorkspaceRequest,
    ReviewWorkspaceRequest,
    WorkspaceCandidateView,
    WorkspaceTestRequest,
)
from .workspace_publication_service import WorkspacePublicationService
from .workspace_publication_views import WorkspacePublicationState
from .publication_evidence import (
    PublicationTestRun,
    WorkspacePublicationEvidenceService,
)
from .channel_binding import AccountAgentBinding


class SafePublicationRoute(SafeConfigurationRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except DomainError as error:
                if error.status != 429:
                    raise
                return JSONResponse(
                    status_code=429,
                    content=error.to_problem_details(
                        correlation_id=str(request.state.correlation_id)
                    ),
                    headers={"Retry-After": "3600"},
                    media_type="application/problem+json",
                )

        return handler


router = APIRouter(
    prefix="/admin/agent-workspace/companies/{tenant_id}/agents/{agent_id}/publication",
    tags=["platform-admin-agent-publication"],
    route_class=SafePublicationRoute,
)


def context(request: Request, tenant_id: UUID, actor_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id, actor_id, "platform_admin", request.state.correlation_id
    )


@router.get("", response_model=WorkspacePublicationState)
async def state(
    tenant_id: UUID,
    agent_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
    cursor: str | None = Query(None, max_length=256),
    limit: int = Query(20, ge=1, le=100),
    section: Literal["candidates", "runs", "accounts", "versions"] = "candidates",
) -> WorkspacePublicationState:
    settings = request.app.state.settings
    return await WorkspacePublicationService(
        session,
        context(request, tenant_id, principal.user_id),
        code_digest=settings.agent_publication_code_digest,
        compatible_versions=settings.agent_publication_compatible_versions,
    ).read_state(agent_id, cursor=cursor, limit=limit, section=section)


@router.post("/candidates", response_model=WorkspaceCandidateView)
async def prepare(
    tenant_id: UUID,
    agent_id: UUID,
    payload: PrepareWorkspaceRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> WorkspaceCandidateView:
    return await WorkspacePublicationService(
        session,
        context(request, tenant_id, principal.user_id),
        code_digest=request.app.state.settings.agent_publication_code_digest,
    ).prepare(agent_id=agent_id, **payload.model_dump())


class PreviewRequest(WorkspaceTestRequest):
    run_kind: Literal["PREVIEW"] = "PREVIEW"


class ScenariosRequest(WorkspaceTestRequest):
    run_kind: Literal["SCENARIOS"] = "SCENARIOS"


@router.post(
    "/candidates/{version_id}/tests", response_model=PublicationTestRun, status_code=202
)
async def tests(
    tenant_id: UUID,
    agent_id: UUID,
    version_id: UUID,
    payload: ScenariosRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> PublicationTestRun:
    return await WorkspacePublicationEvidenceService(
        session,
        context(request, tenant_id, principal.user_id),
        code_digest=request.app.state.settings.agent_publication_code_digest,
    ).request(agent_id, version_id, payload)


@router.post(
    "/candidates/{version_id}/preview",
    response_model=PublicationTestRun,
    status_code=202,
)
async def preview(
    tenant_id: UUID,
    agent_id: UUID,
    version_id: UUID,
    payload: PreviewRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> PublicationTestRun:
    return await WorkspacePublicationEvidenceService(
        session,
        context(request, tenant_id, principal.user_id),
        code_digest=request.app.state.settings.agent_publication_code_digest,
    ).request(agent_id, version_id, payload)


@router.get("/tests/{run_id}", response_model=PublicationTestRun)
async def read_test(
    tenant_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> PublicationTestRun:
    return await WorkspacePublicationEvidenceService(
        session,
        context(request, tenant_id, principal.user_id),
        code_digest=request.app.state.settings.agent_publication_code_digest,
    ).read(agent_id, run_id)


@router.post("/tests/{run_id}/review", response_model=PublicationTestRun)
async def review(
    tenant_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    payload: ReviewWorkspaceRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> PublicationTestRun:
    return await WorkspacePublicationEvidenceService(
        session,
        context(request, tenant_id, principal.user_id),
        code_digest=request.app.state.settings.agent_publication_code_digest,
    ).review(agent_id, run_id, **payload.model_dump())


@router.post("/publish", response_model=AccountAgentBinding)
async def publish(
    tenant_id: UUID,
    agent_id: UUID,
    payload: PublishWorkspaceRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AccountAgentBinding:
    settings = request.app.state.settings
    return await WorkspacePublicationService(
        session,
        context(request, tenant_id, principal.user_id),
        code_digest=settings.agent_publication_code_digest,
        compatible_versions=settings.agent_publication_compatible_versions,
    ).publish(agent_id=agent_id, **payload.model_dump())


@router.post("/rollback", response_model=AccountAgentBinding)
async def rollback(
    tenant_id: UUID,
    agent_id: UUID,
    payload: RollbackWorkspaceRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AccountAgentBinding:
    settings = request.app.state.settings
    return await WorkspacePublicationService(
        session,
        context(request, tenant_id, principal.user_id),
        code_digest=settings.agent_publication_code_digest,
        compatible_versions=settings.agent_publication_compatible_versions,
    ).rollback(agent_id=agent_id, **payload.model_dump())
