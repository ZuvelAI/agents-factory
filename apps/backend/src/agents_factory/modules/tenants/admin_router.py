from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, status
from pydantic import BaseModel, Field

from agents_factory.common.errors import DomainError
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.tenants.models import Tenant, TenantStatus
from agents_factory.modules.tenants.repository import TenantRepository
from agents_factory.modules.tenants.service import TenantService


router = APIRouter(prefix="/admin/tenants", tags=["platform-admin-tenants"])


class TenantCreateRequest(BaseModel):
    slug: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    name: str = Field(min_length=1, max_length=200)


class TenantResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    status: TenantStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_tenant(cls, tenant: Tenant) -> TenantResponse:
        return cls(
            id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            status=tenant.status,
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
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
        idempotency_key=idempotency_key,
    )
    return TenantResponse.from_tenant(tenant)


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
