from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import ActorType, TenantContext
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.tenants.models import Tenant
from agents_factory.modules.tenants.repository import TenantRepository


class TenantService:
    def __init__(self, session: AsyncSession) -> None:
        self._tenants = TenantRepository(session)
        self._audit = AuditService(session)
        self._outbox = OutboxService(session)

    async def create_tenant(
        self,
        *,
        slug: str,
        name: str,
        legal_name: str | None = None,
        industry: str | None = None,
        timezone: str | None = None,
        locale: Literal["es-CO", "en-US"] | None = None,
        actor_id: UUID | None,
        actor_type: ActorType,
        correlation_id: UUID,
        idempotency_key: str,
    ) -> Tenant:
        tenant = Tenant.new(
            slug=slug,
            name=name,
            legal_name=legal_name,
            industry=industry,
            timezone=timezone,
            locale=locale,
        )
        context = TenantContext(
            tenant_id=tenant.id,
            actor_id=actor_id,
            actor_type=actor_type,
            correlation_id=correlation_id,
        )
        await self._tenants.set_tenant_context(tenant.id)
        created = await self._tenants.create(tenant)
        await self._audit.record(
            context=context,
            event_type="tenant.created",
            entity_type="tenant",
            entity_id=tenant.id,
            payload={"slug": slug},
        )
        await self._outbox.enqueue(
            context=context,
            idempotency_key=idempotency_key,
            topic="tenant.created",
            payload={"tenant_id": str(tenant.id)},
        )
        return created
