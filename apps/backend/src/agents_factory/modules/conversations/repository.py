from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.conversations.models import (
    Conversation,
    ConversationControlState,
    Message,
)


@dataclass(frozen=True, slots=True)
class InboundEvent:
    id: UUID
    tenant_id: UUID
    whatsapp_account_id: UUID
    provider_message_id: str
    sender_wa_id: str
    message_type: str
    provider_timestamp: datetime
    content: dict[str, object]


@dataclass(frozen=True, slots=True)
class PersistedMessage:
    message: Message
    created: bool


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_inbound_event(
        self,
        *,
        context: TenantContext,
        event_id: UUID,
    ) -> InboundEvent | None:
        await set_tenant_context(self._session, context.tenant_id)
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, tenant_id, whatsapp_account_id, "
                        "whatsapp_message_id, sender_wa_id, message_type, "
                        "provider_timestamp, normalized_content "
                        "FROM public.whatsapp_webhook_events "
                        "WHERE id = :event_id AND tenant_id = :tenant_id"
                    ),
                    {"event_id": event_id, "tenant_id": context.tenant_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return InboundEvent(
            id=cast(UUID, row["id"]),
            tenant_id=cast(UUID, row["tenant_id"]),
            whatsapp_account_id=cast(UUID, row["whatsapp_account_id"]),
            provider_message_id=cast(str, row["whatsapp_message_id"]),
            sender_wa_id=cast(str, row["sender_wa_id"]),
            message_type=cast(str, row["message_type"]),
            provider_timestamp=cast(datetime, row["provider_timestamp"]),
            content=cast(dict[str, object], row["normalized_content"]),
        )

    async def get_or_create_for_event(
        self,
        *,
        context: TenantContext,
        event: InboundEvent,
    ) -> tuple[Conversation, bool]:
        await set_tenant_context(self._session, context.tenant_id)
        conversation_id = new_uuid7()
        created_id = await self._session.scalar(
            text(
                "INSERT INTO public.conversations "
                "(id, tenant_id, whatsapp_account_id, customer_wa_id) "
                "VALUES (:id, :tenant_id, :account_id, :customer_wa_id) "
                "ON CONFLICT (tenant_id, whatsapp_account_id, customer_wa_id) "
                "DO NOTHING RETURNING id"
            ),
            {
                "id": conversation_id,
                "tenant_id": context.tenant_id,
                "account_id": event.whatsapp_account_id,
                "customer_wa_id": event.sender_wa_id,
            },
        )
        created = created_id is not None
        if created:
            await self._session.execute(
                text(
                    "INSERT INTO public.conversation_state_events "
                    "(id, tenant_id, conversation_id, from_state, to_state, "
                    "version, actor_id, actor_type, reason) "
                    "VALUES (:id, :tenant_id, :conversation_id, NULL, "
                    "'AI_ACTIVE', 1, :actor_id, :actor_type, 'inbound_opened')"
                ),
                {
                    "id": new_uuid7(),
                    "tenant_id": context.tenant_id,
                    "conversation_id": created_id,
                    "actor_id": context.actor_id,
                    "actor_type": context.actor_type,
                },
            )
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, tenant_id, whatsapp_account_id, customer_wa_id, "
                        "control_state, state_version, opened_at, closed_at "
                        "FROM public.conversations WHERE tenant_id = :tenant_id "
                        "AND whatsapp_account_id = :account_id "
                        "AND customer_wa_id = :customer_wa_id FOR UPDATE"
                    ),
                    {
                        "tenant_id": context.tenant_id,
                        "account_id": event.whatsapp_account_id,
                        "customer_wa_id": event.sender_wa_id,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _conversation_from_row(row), created

    async def add_inbound_message(
        self,
        *,
        context: TenantContext,
        conversation: Conversation,
        event: InboundEvent,
    ) -> PersistedMessage:
        await set_tenant_context(self._session, context.tenant_id)
        existing = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, tenant_id, conversation_id, source_event_id, "
                        "provider_message_id, message_type, content, "
                        "provider_timestamp, arrival_sequence FROM public.messages "
                        "WHERE tenant_id = :tenant_id AND source_event_id = :event_id"
                    ),
                    {"tenant_id": context.tenant_id, "event_id": event.id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            return PersistedMessage(
                message=_message_from_row(existing),
                created=False,
            )

        next_sequence = await self._session.scalar(
            text(
                "SELECT coalesce(max(arrival_sequence), 0) + 1 "
                "FROM public.messages WHERE tenant_id = :tenant_id "
                "AND conversation_id = :conversation_id"
            ),
            {
                "tenant_id": context.tenant_id,
                "conversation_id": conversation.id,
            },
        )
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO public.messages "
                        "(id, tenant_id, conversation_id, source_event_id, direction, "
                        "sender_type, provider_message_id, message_type, content, "
                        "provider_timestamp, arrival_sequence) VALUES "
                        "(:id, :tenant_id, :conversation_id, :source_event_id, "
                        "'inbound', 'customer', :provider_message_id, :message_type, "
                        ":content, :provider_timestamp, :arrival_sequence) "
                        "RETURNING id, tenant_id, conversation_id, source_event_id, "
                        "provider_message_id, message_type, content, "
                        "provider_timestamp, arrival_sequence"
                    ).bindparams(bindparam("content", type_=JSONB)),
                    {
                        "id": new_uuid7(),
                        "tenant_id": context.tenant_id,
                        "conversation_id": conversation.id,
                        "source_event_id": event.id,
                        "provider_message_id": event.provider_message_id,
                        "message_type": event.message_type,
                        "content": event.content,
                        "provider_timestamp": event.provider_timestamp,
                        "arrival_sequence": next_sequence,
                    },
                )
            )
            .mappings()
            .one()
        )
        return PersistedMessage(message=_message_from_row(row), created=True)

    async def get(
        self,
        *,
        context: TenantContext,
        conversation_id: UUID,
    ) -> Conversation | None:
        await set_tenant_context(self._session, context.tenant_id)
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, tenant_id, whatsapp_account_id, customer_wa_id, "
                        "control_state, state_version, opened_at, closed_at "
                        "FROM public.conversations WHERE id = :conversation_id "
                        "AND tenant_id = :tenant_id"
                    ),
                    {
                        "conversation_id": conversation_id,
                        "tenant_id": context.tenant_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return _conversation_from_row(row)

    async def transition(
        self,
        *,
        context: TenantContext,
        conversation: Conversation,
        target_state: ConversationControlState,
        reason: str,
    ) -> Conversation:
        await set_tenant_context(self._session, context.tenant_id)
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT conversation_id, control_state, state_version, "
                        "opened_at, closed_at FROM "
                        "agents_factory_private.transition_conversation_control("
                        ":event_id, :conversation_id, :expected_state, :target_state, "
                        ":actor_id, :actor_type, :reason)"
                    ),
                    {
                        "event_id": new_uuid7(),
                        "conversation_id": conversation.id,
                        "expected_state": conversation.control_state.value,
                        "target_state": target_state.value,
                        "actor_id": context.actor_id,
                        "actor_type": context.actor_type,
                        "reason": reason,
                    },
                )
            )
            .mappings()
            .one()
        )
        return Conversation(
            id=cast(UUID, row["conversation_id"]),
            tenant_id=context.tenant_id,
            whatsapp_account_id=conversation.whatsapp_account_id,
            customer_wa_id=conversation.customer_wa_id,
            control_state=ConversationControlState(cast(str, row["control_state"])),
            state_version=cast(int, row["state_version"]),
            opened_at=cast(datetime, row["opened_at"]),
            closed_at=cast(datetime | None, row["closed_at"]),
        )


def _conversation_from_row(row: RowMapping) -> Conversation:
    return Conversation(
        id=cast(UUID, row["id"]),
        tenant_id=cast(UUID, row["tenant_id"]),
        whatsapp_account_id=cast(UUID, row["whatsapp_account_id"]),
        customer_wa_id=cast(str, row["customer_wa_id"]),
        control_state=ConversationControlState(cast(str, row["control_state"])),
        state_version=cast(int, row["state_version"]),
        opened_at=cast(datetime, row["opened_at"]),
        closed_at=cast(datetime | None, row["closed_at"]),
    )


def _message_from_row(row: RowMapping) -> Message:
    return Message(
        id=cast(UUID, row["id"]),
        tenant_id=cast(UUID, row["tenant_id"]),
        conversation_id=cast(UUID, row["conversation_id"]),
        source_event_id=cast(UUID, row["source_event_id"]),
        provider_message_id=cast(str, row["provider_message_id"]),
        message_type=cast(str, row["message_type"]),
        content=cast(dict[str, object], row["content"]),
        provider_timestamp=cast(datetime, row["provider_timestamp"]),
        arrival_sequence=cast(int, row["arrival_sequence"]),
    )
