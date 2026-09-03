from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.agent_factory.configuration import AgentConfigurationService
from agents_factory.modules.agent_factory.models import AgentSpecVersion
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.agent_factory.schemas import (
    AgentEditorState,
    AgentPresentationUpdateRequest,
    ApprovalRoutesDraftRequest,
    CapabilityDraftUpdateRequest,
    ConnectorBindingDraftRequest,
    CreateAgentInstanceRequest,
    CreateAgentInstanceResponse,
    CreateCustomerServiceDraftRequest,
    CreateDraftRequest,
    HumanOperationsDraftRequest,
    PolicyDraftUpdateRequest,
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


@router.get("/current", response_model=AgentEditorState | None)
async def read_current_agent_editor(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentEditorState | None:
    return await _service(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
        session=session,
    ).editor_state()


@router.post(
    "/customer-service",
    response_model=CreateAgentInstanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_customer_service_agent(
    tenant_id: UUID,
    payload: CreateCustomerServiceDraftRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> CreateAgentInstanceResponse:
    instance, draft = await _service(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
        session=session,
    ).create_customer_service_draft(business_name=payload.business_name)
    await AuditService(session).record(
        context=_context(request=request, principal=principal, tenant_id=tenant_id),
        event_type="agent_instance.created",
        entity_type="agent_instance",
        entity_id=instance.id,
        payload={"product": instance.product, "draft_version": draft.version_number},
    )
    return CreateAgentInstanceResponse(instance=instance, draft=draft)


@router.post(
    "/{agent_instance_id}/presentation-drafts",
    response_model=AgentSpecVersion,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_presentation_draft(
    tenant_id: UUID,
    agent_instance_id: UUID,
    payload: AgentPresentationUpdateRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    draft = await _service(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
        session=session,
    ).create_presentation_draft(
        agent_instance_id=agent_instance_id,
        update=payload,
    )
    await AuditService(session).record(
        context=_context(request=request, principal=principal, tenant_id=tenant_id),
        event_type="agent_persona.draft_created",
        entity_type="agent_spec_version",
        entity_id=draft.id,
        payload={
            "agent_instance_id": str(agent_instance_id),
            "version_number": draft.version_number,
        },
    )
    return draft


@router.post(
    "/{agent_instance_id}/capability-drafts",
    response_model=AgentSpecVersion,
    status_code=status.HTTP_201_CREATED,
)
async def create_capability_draft(
    tenant_id: UUID,
    agent_instance_id: UUID,
    payload: CapabilityDraftUpdateRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    draft = await _configuration_service(
        request, principal, tenant_id, session
    ).update_capabilities(agent_instance_id=agent_instance_id, request=payload)
    await _audit_configuration(
        session,
        request,
        principal,
        tenant_id,
        draft,
        "agent_capabilities.draft_created",
    )
    return draft


@router.post(
    "/{agent_instance_id}/policy-drafts",
    response_model=AgentSpecVersion,
    status_code=status.HTTP_201_CREATED,
)
async def create_policy_draft(
    tenant_id: UUID,
    agent_instance_id: UUID,
    payload: PolicyDraftUpdateRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    draft = await _configuration_service(
        request, principal, tenant_id, session
    ).update_policies(agent_instance_id=agent_instance_id, request=payload)
    await _audit_configuration(
        session, request, principal, tenant_id, draft, "agent_policy.draft_created"
    )
    return draft


@router.post(
    "/{agent_instance_id}/connector-binding-drafts",
    response_model=AgentSpecVersion,
    status_code=status.HTTP_201_CREATED,
)
async def create_connector_binding_draft(
    tenant_id: UUID,
    agent_instance_id: UUID,
    payload: ConnectorBindingDraftRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    draft = await _configuration_service(
        request, principal, tenant_id, session
    ).bind_connector(agent_instance_id=agent_instance_id, request=payload)
    await _audit_configuration(
        session,
        request,
        principal,
        tenant_id,
        draft,
        "agent_connector_binding.draft_created",
    )
    return draft


@router.post(
    "/{agent_instance_id}/human-operations-drafts",
    response_model=AgentSpecVersion,
    status_code=status.HTTP_201_CREATED,
)
async def create_human_operations_draft(
    tenant_id: UUID,
    agent_instance_id: UUID,
    payload: HumanOperationsDraftRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    draft = await _configuration_service(
        request, principal, tenant_id, session
    ).update_human_operations(agent_instance_id=agent_instance_id, request=payload)
    await _audit_configuration(
        session, request, principal, tenant_id, draft, "agent_handoff.draft_created"
    )
    return draft


@router.post(
    "/{agent_instance_id}/approval-route-drafts",
    response_model=AgentSpecVersion,
    status_code=status.HTTP_201_CREATED,
)
async def create_approval_route_draft(
    tenant_id: UUID,
    agent_instance_id: UUID,
    payload: ApprovalRoutesDraftRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> AgentSpecVersion:
    draft = await _configuration_service(
        request, principal, tenant_id, session
    ).update_approval_routes(agent_instance_id=agent_instance_id, request=payload)
    await _audit_configuration(
        session,
        request,
        principal,
        tenant_id,
        draft,
        "agent_approval_routes.draft_created",
    )
    return draft


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
    context = _context(
        request=request,
        principal=principal,
        tenant_id=tenant_id,
    )
    return AgentSpecLifecycleService(
        repository=AgentSpecRepository(session, context),
        manifest_validator=CapabilityService(
            capabilities=V1_CAPABILITY_REGISTRY,
            connectors=V1_CONNECTOR_CATALOG,
        ),
    )


def _configuration_service(
    request: Request,
    principal: AdminPrincipal,
    tenant_id: UUID,
    session: TransactionSession,
) -> AgentConfigurationService:
    return AgentConfigurationService(
        session,
        _context(request=request, principal=principal, tenant_id=tenant_id),
    )


async def _audit_configuration(
    session: TransactionSession,
    request: Request,
    principal: AdminPrincipal,
    tenant_id: UUID,
    draft: AgentSpecVersion,
    event_type: str,
) -> None:
    await AuditService(session).record(
        context=_context(request=request, principal=principal, tenant_id=tenant_id),
        event_type=event_type,
        entity_type="agent_spec_version",
        entity_id=draft.id,
        payload={"version_number": draft.version_number},
    )


def _context(
    *, request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )
