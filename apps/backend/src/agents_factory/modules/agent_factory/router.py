from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.agent_factory.models import AgentSpecVersion
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.agent_factory.schemas import (
    CreateAgentInstanceRequest,
    CreateAgentInstanceResponse,
    CreateDraftRequest,
    RollbackRequest,
)
from agents_factory.modules.agent_factory.service import AgentSpecLifecycleService
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY
from agents_factory.modules.capabilities.service import CapabilityService
from agents_factory.modules.integrations.registry import V1_CONNECTOR_CATALOG


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/agent-instances",
    tags=["platform-admin-agent-spec"],
)


@router.post(
    "",
    response_model=CreateAgentInstanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_instance(
    tenant_id: UUID,
    payload: CreateAgentInstanceRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> CreateAgentInstanceResponse:
    instance, draft = await _service(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
        session=session,
    ).create_instance(configuration=payload.configuration)
    return CreateAgentInstanceResponse(instance=instance, draft=draft)


@router.post(
    "/{agent_instance_id}/drafts",
    response_model=AgentSpecVersion,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_spec_draft(
    tenant_id: UUID,
    agent_instance_id: UUID,
    payload: CreateDraftRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    return await _service(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
        session=session,
    ).create_draft(
        agent_instance_id=agent_instance_id,
        based_on_version_id=payload.based_on_version_id,
        configuration=payload.configuration,
    )


@router.post("/versions/{version_id}/test", response_model=AgentSpecVersion)
async def promote_agent_spec_to_test(
    tenant_id: UUID,
    version_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    return await _service(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
        session=session,
    ).promote_to_test(version_id)


@router.post("/versions/{version_id}/quality-gate", response_model=AgentSpecVersion)
async def enter_agent_spec_quality_gate(
    tenant_id: UUID,
    version_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    return await _service(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
        session=session,
    ).enter_quality_gate(version_id)


@router.post("/versions/{version_id}/production", response_model=AgentSpecVersion)
async def publish_agent_spec_production(
    tenant_id: UUID,
    version_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    return await _service(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
        session=session,
    ).publish_production(version_id)


@router.post("/{agent_instance_id}/rollback", response_model=AgentSpecVersion)
async def rollback_agent_spec(
    tenant_id: UUID,
    agent_instance_id: UUID,
    payload: RollbackRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    return await _service(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
        session=session,
    ).rollback_to(
        agent_instance_id=agent_instance_id,
        target_version_id=payload.target_version_id,
        current_code_digest=payload.code_digest,
    )


def _service(
    *,
    request: Request,
    principal: AdminPrincipal,
    tenant_id: UUID,
    session: TransactionSession,
) -> AgentSpecLifecycleService:
    context = TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )
    return AgentSpecLifecycleService(
        repository=AgentSpecRepository(session, context),
        manifest_validator=CapabilityService(
            capabilities=V1_CAPABILITY_REGISTRY,
            connectors=V1_CONNECTOR_CATALOG,
        ),
    )
