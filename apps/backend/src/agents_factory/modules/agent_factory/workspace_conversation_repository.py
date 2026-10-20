"""Tenant-scoped SQL for lists, selection and message attribution. Read-only."""

from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.modules.whatsapp.contact_projection import (
    CONTACT_COLUMNS,
    CONTACT_JOINS,
)


CONVERSATIONS = f"""
SELECT c.id,c.whatsapp_account_id AS account_id,c.customer_wa_id,c.control_state,
 {CONTACT_COLUMNS},
 c.updated_at,activity.last_activity_at,
 ARRAY(SELECT DISTINCT v.agent_instance_id FROM public.messages m
   JOIN public.agent_spec_versions v ON (v.tenant_id,v.id)=(m.tenant_id,m.agent_spec_id)
   WHERE m.tenant_id=c.tenant_id AND m.conversation_id=c.id ORDER BY v.agent_instance_id) AS agent_ids
FROM public.conversations c
{CONTACT_JOINS}
LEFT JOIN LATERAL(SELECT greatest(c.updated_at,coalesce(max(m.created_at),c.created_at)) AS last_activity_at
 FROM public.messages m WHERE m.tenant_id=c.tenant_id AND m.conversation_id=c.id) activity ON true
WHERE c.tenant_id=:tenant AND (CAST(:selected AS uuid) IS NULL OR c.id=:selected)
 AND (CAST(:account AS uuid) IS NULL OR c.whatsapp_account_id=:account)
 AND (CAST(:before_at AS timestamptz) IS NULL OR (activity.last_activity_at,c.id)<(:before_at,:before_id))
 AND (CAST(:agent AS uuid) IS NULL OR EXISTS(SELECT 1 FROM public.messages m
   JOIN public.agent_spec_versions v ON (v.tenant_id,v.id)=(m.tenant_id,m.agent_spec_id)
   WHERE m.tenant_id=c.tenant_id AND m.conversation_id=c.id AND v.agent_instance_id=:agent))
ORDER BY activity.last_activity_at DESC,c.id DESC LIMIT :limit
"""


class WorkspaceConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def exists(self, kind: str, tenant: UUID, id: UUID) -> bool:
        tables = {
            "tenant": "tenants",
            "agent": "agent_instances",
            "account": "whatsapp_accounts",
            "conversation": "conversations",
        }
        table = tables[kind]  # Only server-owned keys, never a query parameter.
        predicate = "id=:id" if kind == "tenant" else "tenant_id=:tenant AND id=:id"
        return bool(
            await self.session.scalar(
                text(f"SELECT EXISTS(SELECT 1 FROM public.{table} WHERE {predicate})"),
                {"tenant": tenant, "id": id},
            )
        )

    async def conversations(
        self,
        *,
        tenant: UUID,
        agent: UUID | None,
        account: UUID | None,
        before_at: datetime | None = None,
        before_id: UUID | None = None,
        selected: UUID | None = None,
        limit: int = 21,
    ) -> list[dict[str, Any]]:
        rows = await self.session.execute(
            text(CONVERSATIONS),
            {
                "tenant": tenant,
                "agent": agent,
                "account": account,
                "before_at": before_at,
                "before_id": before_id,
                "selected": selected,
                "limit": limit,
            },
        )
        return [dict(r) for r in rows.mappings()]

    async def message_sequence(
        self, tenant: UUID, conversation: UUID, id: UUID
    ) -> int | None:
        value = await self.session.scalar(
            text(
                "SELECT arrival_sequence FROM public.messages WHERE tenant_id=:tenant AND conversation_id=:conversation AND id=:id"
            ),
            {"tenant": tenant, "conversation": conversation, "id": id},
        )
        return int(value) if value is not None else None

    async def messages(
        self,
        *,
        tenant: UUID,
        conversation: UUID,
        after: UUID | None,
        sequence: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = await self.session.execute(
            text(
                "SELECT m.id,m.arrival_sequence,m.direction,m.message_type,m.created_at, "
                "CASE WHEN jsonb_typeof(m.content->'text')='string' THEN m.content->>'text' ELSE NULL END AS text, "
                "v.agent_instance_id AS agent_id,v.id AS agent_spec_id,delivery.status AS delivery_status "
                "FROM public.messages m LEFT JOIN public.agent_spec_versions v ON (v.tenant_id,v.id)=(m.tenant_id,m.agent_spec_id) "
                "LEFT JOIN LATERAL(SELECT o.status FROM public.outbound_messages o WHERE o.tenant_id=m.tenant_id "
                "AND o.conversation_id=m.conversation_id AND o.source_message_id=m.id ORDER BY o.created_at DESC,o.id DESC LIMIT 1) delivery ON true "
                "WHERE m.tenant_id=:tenant AND m.conversation_id=:conversation "
                "AND (CAST(:after AS uuid) IS NULL OR (m.arrival_sequence,m.id)<(:sequence,:after)) "
                "ORDER BY m.arrival_sequence DESC,m.id DESC LIMIT :limit"
            ),
            {
                "tenant": tenant,
                "conversation": conversation,
                "after": after,
                "sequence": sequence,
                "limit": limit,
            },
        )
        return [dict(r) for r in rows.mappings()]
