from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        context: TenantContext,
        event_type: str,
        entity_type: str,
        entity_id: UUID | None,
        payload: Mapping[str, object],
    ) -> UUID:
        await set_tenant_context(self._session, context.tenant_id)
        event_id = new_uuid7()
        statement = text(
            "INSERT INTO public.audit_events "
            "(id, tenant_id, actor_id, actor_type, event_type, entity_type, "
            "entity_id, correlation_id, payload) "
            "VALUES (:id, :tenant_id, :actor_id, :actor_type, :event_type, "
            ":entity_type, :entity_id, :correlation_id, :payload)"
        ).bindparams(bindparam("payload", type_=JSONB))
        await self._session.execute(
            statement,
            {
                "id": event_id,
                "tenant_id": context.tenant_id,
                "actor_id": context.actor_id,
                "actor_type": context.actor_type,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "correlation_id": context.correlation_id,
                "payload": dict(payload),
            },
        )
        return event_id
