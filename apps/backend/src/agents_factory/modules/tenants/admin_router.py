from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.tenants.models import Tenant, TenantStatus
from agents_factory.modules.tenants.onboarding import (
    OnboardingService,
    OnboardingStatus,
)
from agents_factory.modules.tenants.repository import TenantRepository
from agents_factory.modules.tenants.service import TenantService


router = APIRouter(prefix="/admin/tenants", tags=["platform-admin-tenants"])


class TenantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    locale: Literal["es-CO", "en-US"] | None = None


class TenantUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    legal_name: str = Field(min_length=1, max_length=200)
    industry: str = Field(min_length=1, max_length=120)
    timezone: str = Field(min_length=1, max_length=100)
    locale: Literal["es-CO", "en-US"]


class TenantResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    legal_name: str | None
    industry: str | None
    timezone: str | None
    locale: Literal["es-CO", "en-US"] | None
    status: TenantStatus
    revision: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_tenant(cls, tenant: Tenant) -> TenantResponse:
        return cls(
            id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            legal_name=tenant.legal_name,
            industry=tenant.industry,
            timezone=tenant.timezone,
            locale=tenant.locale,
            status=tenant.status,
            revision=tenant.revision,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_tenant(
    payload: TenantCreateRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
) -> TenantResponse:
    tenant = await TenantService(session).create_tenant(
        slug=payload.slug,
        name=payload.name.strip(),
        legal_name=_clean(payload.legal_name),
        industry=_clean(payload.industry),
        timezone=_timezone(payload.timezone),
        locale=payload.locale,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
        idempotency_key=idempotency_key,
    )
    return TenantResponse.from_tenant(tenant)


@router.get("", response_model=tuple[TenantResponse, ...])
async def list_admin_tenants(
    principal: PlatformAdmin,
    session: TransactionSession,
    limit: int = 100,
) -> tuple[TenantResponse, ...]:
    _ = principal
    if not 1 <= limit <= 100:
        raise DomainError(
            type="https://agents-factory.dev/problems/invalid-tenant-query",
            title="Invalid Tenant Query",
            status=422,
            detail="The tenant query is invalid.",
            code="invalid_tenant_query",
        )
    tenants = await TenantRepository(session).list_visible(limit=limit)
    return tuple(TenantResponse.from_tenant(tenant) for tenant in tenants)


@router.get("/{tenant_id}", response_model=TenantResponse)
async def read_admin_tenant(
    tenant_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> TenantResponse:
    _ = principal
    tenant = await TenantRepository(session).get(tenant_id)
    if tenant is None:
        raise DomainError(
            type="https://agents-factory.dev/problems/tenant-not-found",
            title="Tenant Not Found",
            status=404,
            detail="The requested tenant does not exist.",
            code="tenant_not_found",
        )
    return TenantResponse.from_tenant(tenant)


@router.get("/{tenant_id}/onboarding", response_model=OnboardingStatus)
async def read_tenant_onboarding(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> OnboardingStatus:
    return await OnboardingService(
        session,
        TenantContext(
            tenant_id=tenant_id,
            actor_id=principal.user_id,
            actor_type="platform_admin",
            correlation_id=request.state.correlation_id,
        ),
    ).status()


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_admin_tenant(
    tenant_id: UUID,
    payload: TenantUpdateRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> TenantResponse:
    timezone = _timezone(payload.timezone)
    repository = TenantRepository(session)
    tenant = await repository.update_profile(
        tenant_id=tenant_id,
        expected_revision=payload.expected_revision,
        name=payload.name.strip(),
        legal_name=payload.legal_name.strip(),
        industry=payload.industry.strip(),
        timezone=timezone or payload.timezone,
        locale=payload.locale,
    )
    if tenant is None:
        existing = await repository.get(tenant_id)
        if existing is None:
            raise _tenant_not_found()
        raise DomainError(
            type="https://agents-factory.dev/problems/tenant-profile-stale",
            title="Tenant Profile Changed",
            status=409,
            detail="The tenant profile changed. Reload it before saving again.",
            code="tenant_profile_stale",
        )
    await AuditService(session).record(
        context=TenantContext(
            tenant_id, principal.user_id, "platform_admin", request.state.correlation_id
        ),
        event_type="tenant.profile_updated",
        entity_type="tenant",
        entity_id=tenant_id,
        payload={"revision": tenant.revision},
    )
    return TenantResponse.from_tenant(tenant)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _timezone(value: str | None) -> str | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        raise DomainError(
            type="https://agents-factory.dev/problems/invalid-timezone",
            title="Invalid Timezone",
            status=422,
            detail="Use a valid IANA timezone.",
            code="invalid_timezone",
        ) from None
    return cleaned


def _tenant_not_found() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/tenant-not-found",
        title="Tenant Not Found",
        status=404,
        detail="The requested tenant does not exist.",
        code="tenant_not_found",
    )
