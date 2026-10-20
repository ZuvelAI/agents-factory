from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from agents_factory.common.errors import DomainError
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.audio_ingestion.repository import AudioRepository
from agents_factory.common.security import PlatformAdmin
from agents_factory.dependencies import TransactionSession
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.contact_projection import (
    CONTACT_COLUMNS,
    CONTACT_JOINS,
)
from agents_factory.modules.tenants.models import Tenant, TenantStatus
from agents_factory.modules.tenants.repository import TenantRepository
from agents_factory.modules.tenants.service import TenantService


router = APIRouter(prefix="/admin/tenants", tags=["platform-admin-tenants"])


class ConversationReadResponse(BaseModel):
    id: UUID
    customer_wa_id: str
    contact_name: str | None = None
    contact_username: str | None = None
    contact_phone_number: str | None = None
    control_state: str
    updated_at: datetime


class MessageReadResponse(BaseModel):
    id: UUID
    direction: str
    message_type: str
    text: str | None
    created_at: datetime
    audio_state: str | None = None
    transcription_id: UUID | None = None
    transcription_digest: str | None = None
    text_source: str | None = None


@router.get("/{tenant_id}/conversations", response_model=list[ConversationReadResponse])
async def list_admin_conversations(
    tenant_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[ConversationReadResponse]:
    _ = principal
    await set_tenant_context(session, tenant_id)
    rows = await session.execute(
        text(
            f"SELECT c.id, c.customer_wa_id, c.control_state, c.updated_at, {CONTACT_COLUMNS} "
            f"FROM public.conversations c {CONTACT_JOINS} WHERE c.tenant_id=:tenant "
            "ORDER BY c.updated_at DESC, c.id DESC LIMIT :limit OFFSET :offset"
        ),
        {"tenant": tenant_id, "limit": limit, "offset": offset},
    )
    return [
        ConversationReadResponse.model_validate(dict(row)) for row in rows.mappings()
    ]


@router.get(
    "/{tenant_id}/conversations/{conversation_id}/messages",
    response_model=list[MessageReadResponse],
)
async def list_admin_conversation_messages(
    tenant_id: UUID,
    conversation_id: UUID,
    principal: PlatformAdmin,
    session: TransactionSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[MessageReadResponse]:
    _ = principal
    found = await session.scalar(
        text(
            "SELECT id FROM public.conversations WHERE id=:conversation AND tenant_id=:tenant"
        ),
        {"conversation": conversation_id, "tenant": tenant_id},
    )
    if found is None:
        raise DomainError(
            type="https://agents-factory.dev/problems/conversation-not-found",
            title="Conversation Not Found",
            status=404,
            detail="The conversation was not found for this tenant.",
            code="conversation_not_found",
        )
    rows = await session.execute(
        text(
            "SELECT m.id, m.direction, m.message_type, "
            "CASE WHEN jsonb_typeof(m.content->'text')='string' THEN m.content->>'text' ELSE NULL END AS text, m.created_at "
            "FROM public.messages m JOIN public.conversations c ON c.id=m.conversation_id AND c.tenant_id=m.tenant_id "
            "WHERE m.tenant_id=:tenant AND c.tenant_id=:tenant AND c.id=:conversation "
            "ORDER BY m.arrival_sequence DESC, m.id DESC LIMIT :limit OFFSET :offset"
        ),
        {
            "tenant": tenant_id,
            "conversation": conversation_id,
            "limit": limit,
            "offset": offset,
        },
    )
    return list(
        reversed(
            [
                MessageReadResponse.model_validate(row)
                for row in await AudioRepository(
                    session, TenantContext(tenant_id, None, "system", new_uuid7())
                ).project_rows([dict(row) for row in rows.mappings()])
            ]
        )
    )


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


@router.get("", response_model=list[TenantResponse])
async def list_admin_tenants(
    principal: PlatformAdmin,
    session: TransactionSession,
) -> list[TenantResponse]:
    _ = principal
    return [
        TenantResponse.from_tenant(tenant)
        for tenant in await TenantRepository(session).list_visible()
    ]


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
