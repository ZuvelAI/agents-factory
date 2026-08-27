from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.conversations.models import (
    AwaitingHumanPolicy,
    Conversation,
    ConversationControlState,
    ConversationIngestResult,
)
from agents_factory.modules.conversations.repository import ConversationRepository
from agents_factory.modules.conversations.state_machine import ConversationStateMachine


class ConversationNotFound(LookupError):
    pass


class InboundEventNotFound(LookupError):
    pass


class ConversationService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        context: TenantContext,
        awaiting_human_policy: AwaitingHumanPolicy,
        reopen_closed_on_inbound: bool = True,
    ) -> None:
        self._context = context
        self._repository = ConversationRepository(session)
        self._audit = AuditService(session)
        self._outbox = OutboxService(session)
        self._awaiting_human_policy = awaiting_human_policy
        self._reopen_closed_on_inbound = reopen_closed_on_inbound
        self._state_machine = ConversationStateMachine()

    async def ingest(self, event_id: UUID) -> ConversationIngestResult:
        event = await self._repository.get_inbound_event(
            context=self._context,
            event_id=event_id,
        )
        if event is None:
            raise InboundEventNotFound(event_id)
        conversation, _ = await self._repository.get_or_create_for_event(
            context=self._context,
            event=event,
        )
        persisted = await self._repository.add_inbound_message(
            context=self._context,
            conversation=conversation,
            event=event,
        )
        if not persisted.created:
            return ConversationIngestResult(
                conversation_id=conversation.id,
                message_id=persisted.message.id,
                message_created=False,
                control_state=conversation.control_state,
                response_queued=False,
            )

        if conversation.control_state == ConversationControlState.CLOSED:
            target = self._state_machine.reopen_for_inbound(
                conversation.control_state,
                enabled=self._reopen_closed_on_inbound,
            )
            if target != conversation.control_state:
                conversation = await self._transition(
                    conversation=conversation,
                    target_state=target,
                    reason="inbound_reopened",
                )

        await self._audit.record(
            context=self._context,
            event_type="conversation.message.received",
            entity_type="message",
            entity_id=persisted.message.id,
            payload={
                "conversation_id": str(conversation.id),
                "message_type": persisted.message.message_type,
                "arrival_sequence": persisted.message.arrival_sequence,
            },
        )
        response_queued = self._state_machine.may_ai_respond(
            state=conversation.control_state,
            awaiting_human_policy=self._awaiting_human_policy,
        )
        if response_queued:
            await self._outbox.enqueue(
                context=self._context,
                idempotency_key=f"agent.turn:{persisted.message.id}",
                topic="agent.turn",
                payload={
                    "aggregate_id": str(conversation.id),
                    "conversation_id": str(conversation.id),
                    "inbound_message_id": str(persisted.message.id),
                },
            )
        return ConversationIngestResult(
            conversation_id=conversation.id,
            message_id=persisted.message.id,
            message_created=True,
            control_state=conversation.control_state,
            response_queued=response_queued,
        )

    async def request_handoff(
        self,
        *,
        conversation_id: UUID,
        reason: str,
    ) -> Conversation:
        conversation = await self._require_conversation(conversation_id)
        target = self._state_machine.request_handoff(conversation.control_state)
        return await self._transition(
            conversation=conversation,
            target_state=target,
            reason=reason,
        )

    async def activate_human(
        self,
        *,
        conversation_id: UUID,
        reason: str,
    ) -> Conversation:
        conversation = await self._require_conversation(conversation_id)
        target = self._state_machine.activate_human(conversation.control_state)
        return await self._transition(
            conversation=conversation,
            target_state=target,
            reason=reason,
        )

    async def close_conversation(
        self,
        *,
        conversation_id: UUID,
        reason: str,
    ) -> Conversation:
        conversation = await self._require_conversation(conversation_id)
        target = self._state_machine.close_conversation(conversation.control_state)
        return await self._transition(
            conversation=conversation,
            target_state=target,
            reason=reason,
        )

    async def may_ai_respond(self, conversation_id: UUID) -> bool:
        conversation = await self._require_conversation(conversation_id)
        return self._state_machine.may_ai_respond(
            state=conversation.control_state,
            awaiting_human_policy=self._awaiting_human_policy,
        )

    async def _require_conversation(self, conversation_id: UUID) -> Conversation:
        conversation = await self._repository.get(
            context=self._context,
            conversation_id=conversation_id,
        )
        if conversation is None:
            raise ConversationNotFound(conversation_id)
        return conversation

    async def _transition(
        self,
        *,
        conversation: Conversation,
        target_state: ConversationControlState,
        reason: str,
    ) -> Conversation:
        transitioned = await self._repository.transition(
            context=self._context,
            conversation=conversation,
            target_state=target_state,
            reason=reason,
        )
        await self._audit.record(
            context=self._context,
            event_type="conversation.control.transitioned",
            entity_type="conversation",
            entity_id=conversation.id,
            payload={
                "from_state": conversation.control_state.value,
                "to_state": target_state.value,
                "version": transitioned.state_version,
                "reason": reason,
            },
        )
        return transitioned
