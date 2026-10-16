"""Authorized editing boundary; business logic belongs to configuration services."""

from uuid import UUID
from fastapi import APIRouter
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from .configuration_models import (
    CompanyProfileView,
    CreateAgentRequest,
    CreateCompanyRequest,
    DraftView,
    RefreshCompanyRequest,
    SaveCompanyRequest,
    SaveDraftRequest,
)
from .configuration_service import AgentConfigurationService
from .configuration_import import LegacyConfigurationImportService
from .configuration_models import ImportLegacyRequest
from .configuration_errors import SafeConfigurationRoute

router = APIRouter(
    prefix="/admin/agent-workspace",
    tags=["platform-admin-configuration"],
    route_class=SafeConfigurationRoute,
)


@router.post(
    "/companies/{tenant_id}/agents/{agent_id}/configuration/import-legacy",
    response_model=DraftView,
)
async def import_legacy(
    tenant_id: UUID,
    agent_id: UUID,
    payload: ImportLegacyRequest,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> DraftView:
    return await LegacyConfigurationImportService(session, principal).import_draft(
        tenant_id=tenant_id,
        agent_id=agent_id,
        expected_legacy_revision=payload.expected_legacy_revision,
        expected_company_revision=payload.expected_company_revision,
    )


@router.post("/companies", response_model=CompanyProfileView, status_code=201)
async def create_company(
    payload: CreateCompanyRequest, principal: PlatformAdmin, session: TransactionSession
) -> CompanyProfileView:
    return await AgentConfigurationService(session, principal).create_company(
        **payload.model_dump()
    )


@router.get("/companies/{tenant_id}/profile", response_model=CompanyProfileView)
async def company_profile(
    tenant_id: UUID, principal: PlatformAdmin, session: TransactionSession
) -> CompanyProfileView:
    return await AgentConfigurationService(session, principal).get_company(
        tenant_id=tenant_id
    )


@router.put("/companies/{tenant_id}/profile", response_model=CompanyProfileView)
async def save_company(
    tenant_id: UUID,
    payload: SaveCompanyRequest,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> CompanyProfileView:
    return await AgentConfigurationService(session, principal).save_company(
        tenant_id=tenant_id,
        expected_revision=payload.expected_revision,
        configuration=payload.configuration,
    )


@router.post("/companies/{tenant_id}/agents", response_model=DraftView, status_code=201)
async def create_agent(
    tenant_id: UUID,
    payload: CreateAgentRequest,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> DraftView:
    return await AgentConfigurationService(session, principal).create_agent(
        tenant_id=tenant_id, name=payload.name
    )


@router.get(
    "/companies/{tenant_id}/agents/{agent_id}/configuration", response_model=DraftView
)
async def configuration(
    tenant_id: UUID,
    agent_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> DraftView:
    return await AgentConfigurationService(session, principal).get_draft(
        tenant_id=tenant_id, agent_id=agent_id
    )


@router.put(
    "/companies/{tenant_id}/agents/{agent_id}/configuration", response_model=DraftView
)
async def save_configuration(
    tenant_id: UUID,
    agent_id: UUID,
    payload: SaveDraftRequest,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> DraftView:
    return await AgentConfigurationService(session, principal).save_draft(
        tenant_id=tenant_id,
        agent_id=agent_id,
        expected_revision=payload.expected_revision,
        configuration=payload.configuration,
    )


@router.post(
    "/companies/{tenant_id}/agents/{agent_id}/configuration/refresh-company",
    response_model=DraftView,
)
async def refresh_company(
    tenant_id: UUID,
    agent_id: UUID,
    payload: RefreshCompanyRequest,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> DraftView:
    return await AgentConfigurationService(session, principal).refresh_company(
        tenant_id=tenant_id,
        agent_id=agent_id,
        expected_revision=payload.expected_revision,
        expected_company_revision=payload.expected_company_revision,
    )
