"""Bounded operational messages; historical attribution never uses current bindings."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.database import set_tenant_context
from .publication_service import publication_problem
from .workspace_service import decode_cursor, encode_cursor


class ConversationSummary(BaseModel):
    id: UUID
    account_id: UUID
    customer_wa_id: str
    control_state: str
    updated_at: datetime
    agent_ids: list[UUID]


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    next_cursor: str | None = None


class OperationalMessage(BaseModel):
    id: UUID
    arrival_sequence: int
    direction: str
    message_type: str
    text: str | None
    created_at: datetime
    agent_id: UUID | None
    agent_spec_id: UUID | None
    delivery_status: str | None


class MessagePage(BaseModel):
    items: list[OperationalMessage]
    next_cursor: str | None = None


class WorkspaceConversationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _scope(self, tenant_id: UUID) -> None:
        await set_tenant_context(self.session, tenant_id)
        if not await self.session.scalar(
            text("SELECT EXISTS(SELECT 1 FROM public.tenants WHERE id=:tenant)"),
            {"tenant": tenant_id},
        ):
            raise publication_problem(
                "workspace_not_found", "Empresa no encontrada.", 404
            )

    async def list_conversations(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None = None,
        account_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ConversationPage:
        await self._scope(tenant_id)
        if agent_id is not None and not await self.session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.agent_instances WHERE tenant_id=:tenant AND id=:agent)"
            ),
            {"tenant": tenant_id, "agent": agent_id},
        ):
            raise publication_problem(
                "workspace_not_found", "Agente no encontrado.", 404
            )
        if account_id is not None and not await self.session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.whatsapp_accounts WHERE tenant_id=:tenant AND id=:account)"
            ),
            {"tenant": tenant_id, "account": account_id},
        ):
            raise publication_problem(
                "workspace_not_found", "Cuenta no encontrada.", 404
            )
        rows = list(
            (
                await self.session.execute(
                    text(
                        "SELECT c.id,c.whatsapp_account_id AS account_id,c.customer_wa_id,c.control_state,c.updated_at, "
                        "ARRAY(SELECT DISTINCT v.agent_instance_id FROM public.messages m JOIN public.agent_spec_versions v "
                        "ON (v.tenant_id,v.id)=(m.tenant_id,m.agent_spec_id) WHERE m.tenant_id=c.tenant_id AND m.conversation_id=c.id "
                        "ORDER BY v.agent_instance_id) AS agent_ids "
                        "FROM public.conversations c WHERE c.tenant_id=:tenant "
                        "AND (CAST(:account AS uuid) IS NULL OR c.whatsapp_account_id=:account) "
                        "AND (CAST(:after AS uuid) IS NULL OR c.id<:after) "
                        "AND (CAST(:agent AS uuid) IS NULL OR EXISTS(SELECT 1 FROM public.messages m "
                        "JOIN public.agent_spec_versions v ON (v.tenant_id,v.id)=(m.tenant_id,m.agent_spec_id) "
                        "WHERE m.tenant_id=c.tenant_id AND m.conversation_id=c.id AND v.agent_instance_id=:agent)) "
                        "ORDER BY c.id DESC LIMIT :limit"
                    ),
                    {
                        "tenant": tenant_id,
                        "account": account_id,
                        "agent": agent_id,
                        "after": decode_cursor(cursor),
                        "limit": limit + 1,
                    },
                )
            ).mappings()
        )
        return ConversationPage(
            items=[ConversationSummary(**r) for r in rows[:limit]],
            next_cursor=encode_cursor(rows[limit - 1]["id"])
            if len(rows) > limit
            else None,
        )

    async def list_messages(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        cursor: str | None = None,
        limit: int = 20,
    ) -> MessagePage:
        await self._scope(tenant_id)
        if not await self.session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.conversations WHERE tenant_id=:tenant AND id=:conversation)"
            ),
            {"tenant": tenant_id, "conversation": conversation_id},
        ):
            raise publication_problem(
                "workspace_not_found", "Conversación no encontrada.", 404
            )
        after = decode_cursor(cursor)
        sequence = None
        if after is not None:
            sequence = await self.session.scalar(
                text(
                    "SELECT arrival_sequence FROM public.messages WHERE tenant_id=:tenant AND conversation_id=:conversation AND id=:id"
                ),
                {"tenant": tenant_id, "conversation": conversation_id, "id": after},
            )
            if sequence is None:
                raise publication_problem(
                    "invalid_workspace_cursor", "Cursor de mensajes inválido.", 422
                )
        rows = list(
            (
                await self.session.execute(
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
                        "tenant": tenant_id,
                        "conversation": conversation_id,
                        "after": after,
                        "sequence": sequence,
                        "limit": limit + 1,
                    },
                )
            ).mappings()
        )
        return MessagePage(
            items=[OperationalMessage(**r) for r in reversed(rows[:limit])],
            next_cursor=encode_cursor(rows[limit - 1]["id"])
            if len(rows) > limit
            else None,
        )
