from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from agents_factory.modules.conversations.models import (
    AwaitingHumanPolicy,
    ConversationControlState,
)
from agents_factory.modules.conversations.state_machine import ConversationStateMachine
from agents_factory.modules.runtime.contracts import (
    AgentRuntime,
    AgentSpecSnapshot,
    AgentTurnInput,
    AgentTurnResult,
    ModelConfiguration,
    RuntimeLimits,
    RuntimeTraceMetadata,
    TurnMessage,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.runtime.first_contact import (
    compose_welcome,
    orientation_only,
)


TurnExecutionStatus = Literal[
    "completed",
    "already_processed",
    "blocked_by_conversation_control",
    "inactive_agent_spec",
]


class AgentTurnNotFound(LookupError):
    pass


class AgentSpecProvider(Protocol):
    async def get_active(
        self,
        *,
        tenant_id: UUID,
    ) -> AgentSpecSnapshot | None: ...


class CapabilityRelevanceResolver(Protocol):
    def resolve(
        self,
        *,
        agent_spec: AgentSpecSnapshot,
        inbound_message: TurnMessage,
    ) -> frozenset[str]: ...


class AllActiveCapabilities:
    def resolve(
        self,
        *,
        agent_spec: AgentSpecSnapshot,
        inbound_message: TurnMessage,
    ) -> frozenset[str]:
        _ = inbound_message
        return agent_spec.active_capabilities


class Milestone2AgentSpecProvider:
    """Temporary immutable baseline until Task 12 owns compiled AgentSpec rows."""

    def __init__(self, instructions: str | None = None) -> None:
        self._instructions = instructions or load_customer_service_core_prompt()
        self._digest = hashlib.sha256(self._instructions.encode("utf-8")).hexdigest()

    async def get_active(
        self,
        *,
        tenant_id: UUID,
    ) -> AgentSpecSnapshot:
        return AgentSpecSnapshot(
            id=uuid5(NAMESPACE_URL, f"agents-factory:m2:{tenant_id}"),
            tenant_id=tenant_id,
            version="m2-baseline-v1",
            digest=self._digest,
            product="customer_service",
            product_version="1.0.0",
            instructions=self._instructions,
            active_capabilities=frozenset(),
            permitted_tools=frozenset(),
            model=ModelConfiguration(),
            limits=RuntimeLimits(),
            active=True,
        )


@dataclass(frozen=True, slots=True)
class AgentTurnExecution:
    status: TurnExecutionStatus
    assistant_message_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class _LoadedTurn:
    control_state: ConversationControlState
    messages: tuple[TurnMessage, ...]
    inbound_message: TurnMessage
    superseded_by_human: bool


@dataclass(frozen=True, slots=True)
class _PersistedAssistant:
    message_id: UUID | None
    created: bool
    authority_available: bool


class AgentTurnService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        context: TenantContext,
        runtime: AgentRuntime,
        agent_specs: AgentSpecProvider,
        tools: RuntimeToolRegistry,
        relevance: CapabilityRelevanceResolver | None = None,
        awaiting_human_policy: AwaitingHumanPolicy = AwaitingHumanPolicy.SILENT,
    ) -> None:
        self._session = session
        self._context = context
        self._runtime = runtime
        self._agent_specs = agent_specs
        self._tools = tools
        self._relevance = relevance or AllActiveCapabilities()
        self._awaiting_human_policy = awaiting_human_policy
        self._repository = _RuntimeTurnRepository(session)
        self._state_machine = ConversationStateMachine()
        self._outbox = OutboxService(session)
        self._audit = AuditService(session)

    async def process(
        self,
        *,
        conversation_id: UUID,
        inbound_message_id: UUID,
    ) -> AgentTurnExecution:
        existing = await self._repository.find_assistant_reply(
            context=self._context,
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
        )
        if existing is not None:
            return AgentTurnExecution(
                status="already_processed",
                assistant_message_id=existing,
            )
        loaded = await self._repository.load(
            context=self._context,
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
        )
        if loaded is None:
            raise AgentTurnNotFound

        if loaded.superseded_by_human or not self._may_ai_respond(loaded.control_state):
            return AgentTurnExecution(status="blocked_by_conversation_control")

        agent_spec = await self._agent_specs.get_active(
            tenant_id=self._context.tenant_id,
        )
        if (
            agent_spec is None
            or not agent_spec.active
            or agent_spec.tenant_id != self._context.tenant_id
        ):
            return AgentTurnExecution(status="inactive_agent_spec")

        relevant = self._relevance.resolve(
            agent_spec=agent_spec,
            inbound_message=loaded.inbound_message,
        )
        selected_tools = self._tools.select(
            agent_spec=agent_spec,
            relevant_capabilities=relevant,
        )
        first_contact = bool(
            agent_spec.first_contact_greeting
        ) and await self._repository.is_new_contact(
            context=self._context,
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
            not_before=agent_spec.first_contact_since,
        )
        turn = AgentTurnInput(
            agent_spec=agent_spec,
            messages=loaded.messages,
            tools=selected_tools,
            is_first_contact=first_contact,
            trace=RuntimeTraceMetadata(
                tenant_id=self._context.tenant_id,
                conversation_id=conversation_id,
                inbound_message_id=inbound_message_id,
                correlation_id=self._context.correlation_id,
                agent_spec_id=agent_spec.id,
                agent_spec_digest=agent_spec.digest,
            ),
        )
        result = await self._runtime.run(turn)
        persisted = await self._repository.persist_assistant_reply(
            context=self._context,
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
            agent_spec=agent_spec,
            result=result,
            awaiting_human_policy=self._awaiting_human_policy,
            only_orientation=orientation_only(loaded.inbound_message.text),
        )
        if not persisted.authority_available:
            return AgentTurnExecution(status="blocked_by_conversation_control")
        if persisted.message_id is None:
            raise RuntimeError("assistant persistence produced no identity")
        if not persisted.created:
            return AgentTurnExecution(
                status="already_processed",
                assistant_message_id=persisted.message_id,
            )

        await self._outbox.enqueue(
            context=self._context,
            idempotency_key=f"outbound.text:{persisted.message_id}",
            topic="outbound.text",
            payload={
                "aggregate_id": str(conversation_id),
                "conversation_id": str(conversation_id),
                "message_id": str(persisted.message_id),
            },
        )
        await self._audit.record(
            context=self._context,
            event_type="agent.turn.completed",
            entity_type="message",
            entity_id=persisted.message_id,
            payload={
                "conversation_id": str(conversation_id),
                "inbound_message_id": str(inbound_message_id),
                "agent_spec_id": str(agent_spec.id),
                "agent_spec_version": agent_spec.version,
                "agent_spec_digest": agent_spec.digest,
                "model": agent_spec.model.model,
                "tool_names": [call.tool_name for call in result.tool_calls],
                "total_tokens": result.usage.total_tokens,
            },
        )
        return AgentTurnExecution(
            status="completed",
            assistant_message_id=persisted.message_id,
        )

    def _may_ai_respond(self, state: ConversationControlState) -> bool:
        return self._state_machine.may_ai_respond(
            state=state,
            awaiting_human_policy=self._awaiting_human_policy,
        )


class _RuntimeTurnRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(
        self,
        *,
        context: TenantContext,
        conversation_id: UUID,
        inbound_message_id: UUID,
    ) -> _LoadedTurn | None:
        await set_tenant_context(self._session, context.tenant_id)
        state = await self._session.scalar(
            text(
                "SELECT control_state FROM public.conversations "
                "WHERE tenant_id = :tenant_id AND id = :conversation_id"
            ),
            {
                "tenant_id": context.tenant_id,
                "conversation_id": conversation_id,
            },
        )
        if not isinstance(state, str):
            return None
        inbound_row = (
            (
                await self._session.execute(
                    text(
                        "SELECT inbound.id, inbound.direction, inbound.sender_type, "
                        "inbound.message_type, inbound.content, inbound.arrival_sequence, "
                        "account.mode='COEXISTENCE' AND EXISTS ("
                        "SELECT 1 FROM public.messages AS human "
                        "WHERE human.tenant_id=inbound.tenant_id "
                        "AND human.conversation_id=inbound.conversation_id "
                        "AND human.direction='outbound' AND human.sender_type='human' "
                        "AND (human.arrival_sequence > inbound.arrival_sequence "
                        "OR human.provider_timestamp >= inbound.provider_timestamp)"
                        ") AS superseded_by_human "
                        "FROM public.messages AS inbound "
                        "JOIN public.conversations AS conversation "
                        "ON conversation.tenant_id=inbound.tenant_id "
                        "AND conversation.id=inbound.conversation_id "
                        "JOIN public.whatsapp_accounts AS account "
                        "ON account.tenant_id=conversation.tenant_id "
                        "AND account.id=conversation.whatsapp_account_id "
                        "WHERE inbound.tenant_id = :tenant_id "
                        "AND inbound.conversation_id = :conversation_id "
                        "AND inbound.id = :inbound_message_id "
                        "AND inbound.direction = 'inbound' "
                        "AND inbound.sender_type = 'customer'"
                    ),
                    {
                        "tenant_id": context.tenant_id,
                        "conversation_id": conversation_id,
                        "inbound_message_id": inbound_message_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if inbound_row is None:
            return None
        prior_rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, direction, sender_type, message_type, content "
                        "FROM public.messages WHERE tenant_id = :tenant_id "
                        "AND conversation_id = :conversation_id "
                        "AND arrival_sequence < :arrival_sequence "
                        "ORDER BY provider_timestamp, arrival_sequence"
                    ),
                    {
                        "tenant_id": context.tenant_id,
                        "conversation_id": conversation_id,
                        "arrival_sequence": inbound_row["arrival_sequence"],
                    },
                )
            )
            .mappings()
            .all()
        )
        inbound = _turn_message(inbound_row)
        messages = tuple(_turn_message(row) for row in prior_rows) + (inbound,)
        return _LoadedTurn(
            control_state=ConversationControlState(state),
            messages=messages,
            inbound_message=inbound,
            superseded_by_human=bool(inbound_row["superseded_by_human"]),
        )

    async def find_assistant_reply(
        self,
        *,
        context: TenantContext,
        conversation_id: UUID,
        inbound_message_id: UUID,
    ) -> UUID | None:
        await set_tenant_context(self._session, context.tenant_id)
        value = await self._session.scalar(
            text(
                "SELECT reply.id FROM public.messages AS reply "
                "JOIN public.messages AS inbound "
                "ON inbound.tenant_id = reply.tenant_id "
                "AND inbound.id = reply.in_reply_to_message_id "
                "WHERE reply.tenant_id = :tenant_id "
                "AND reply.conversation_id = :conversation_id "
                "AND inbound.conversation_id = :conversation_id "
                "AND inbound.id = :inbound_message_id"
            ),
            {
                "tenant_id": context.tenant_id,
                "conversation_id": conversation_id,
                "inbound_message_id": inbound_message_id,
            },
        )
        return cast(UUID | None, value)

    async def persist_assistant_reply(
        self,
        *,
        context: TenantContext,
        conversation_id: UUID,
        inbound_message_id: UUID,
        agent_spec: AgentSpecSnapshot,
        result: AgentTurnResult,
        awaiting_human_policy: AwaitingHumanPolicy,
        only_orientation: bool = False,
    ) -> _PersistedAssistant:
        await set_tenant_context(self._session, context.tenant_id)
        authority = (
            (
                await self._session.execute(
                    text(
                        "SELECT conversation.control_state, "
                        "account.mode='COEXISTENCE' AND EXISTS ("
                        "SELECT 1 FROM public.messages AS inbound "
                        "JOIN public.messages AS human "
                        "ON human.tenant_id=inbound.tenant_id "
                        "AND human.conversation_id=inbound.conversation_id "
                        "AND human.direction='outbound' AND human.sender_type='human' "
                        "AND (human.arrival_sequence > inbound.arrival_sequence "
                        "OR human.provider_timestamp >= inbound.provider_timestamp) "
                        "WHERE inbound.tenant_id=:tenant_id "
                        "AND inbound.conversation_id=:conversation_id "
                        "AND inbound.id=:inbound_message_id"
                        ") AS superseded_by_human "
                        "FROM public.conversations AS conversation "
                        "JOIN public.whatsapp_accounts AS account "
                        "ON account.tenant_id=conversation.tenant_id "
                        "AND account.id=conversation.whatsapp_account_id "
                        "WHERE conversation.tenant_id=:tenant_id "
                        "AND conversation.id=:conversation_id FOR UPDATE OF conversation"
                    ),
                    {
                        "tenant_id": context.tenant_id,
                        "conversation_id": conversation_id,
                        "inbound_message_id": inbound_message_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if authority is None:
            raise AgentTurnNotFound
        if authority[
            "superseded_by_human"
        ] or not ConversationStateMachine.may_ai_respond(
            state=ConversationControlState(authority["control_state"]),
            awaiting_human_policy=awaiting_human_policy,
        ):
            return _PersistedAssistant(
                message_id=None,
                created=False,
                authority_available=False,
            )
        existing = await self.find_assistant_reply(
            context=context,
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
        )
        if existing is not None:
            return _PersistedAssistant(
                message_id=existing,
                created=False,
                authority_available=True,
            )
        arrival_sequence = await self._session.scalar(
            text(
                "SELECT coalesce(max(arrival_sequence), 0) + 1 "
                "FROM public.messages WHERE tenant_id = :tenant_id "
                "AND conversation_id = :conversation_id"
            ),
            {
                "tenant_id": context.tenant_id,
                "conversation_id": conversation_id,
            },
        )
        message_id = new_uuid7()
        if agent_spec.first_contact_greeting:
            # Recheck under the conversation lock: another turn/human/history may
            # have arrived while the model was running. No separate welcome job.
            first_contact = await self.is_new_contact(
                context=context,
                conversation_id=conversation_id,
                inbound_message_id=inbound_message_id,
                not_before=agent_spec.first_contact_since,
            )
            result = replace(
                result,
                output_text=compose_welcome(
                    result.output_text,
                    agent_spec.first_contact_greeting,
                    first_contact=first_contact,
                    only_orientation=only_orientation,
                ),
            )
        runtime_metadata = _runtime_metadata(agent_spec=agent_spec, result=result)
        if agent_spec.first_contact_greeting:
            runtime_metadata["first_contact_greeting_applied"] = first_contact
        created_id = await self._session.scalar(
            text(
                "INSERT INTO public.messages "
                "(id, tenant_id, conversation_id, in_reply_to_message_id, "
                "direction, sender_type, message_type, content, "
                "provider_timestamp, arrival_sequence, agent_spec_id, "
                "agent_spec_version, runtime_metadata) VALUES "
                "(:id, :tenant_id, :conversation_id, :inbound_message_id, "
                "'outbound', 'ai', 'text', :content, :provider_timestamp, "
                ":arrival_sequence, :agent_spec_id, :agent_spec_version, "
                ":runtime_metadata) ON CONFLICT "
                "(tenant_id, in_reply_to_message_id) DO NOTHING RETURNING id"
            ).bindparams(
                bindparam("content", type_=JSONB),
                bindparam("runtime_metadata", type_=JSONB),
            ),
            {
                "id": message_id,
                "tenant_id": context.tenant_id,
                "conversation_id": conversation_id,
                "inbound_message_id": inbound_message_id,
                "content": {"text": result.output_text},
                "provider_timestamp": datetime.now(UTC),
                "arrival_sequence": arrival_sequence,
                "agent_spec_id": agent_spec.id,
                "agent_spec_version": agent_spec.version,
                "runtime_metadata": runtime_metadata,
            },
        )
        if created_id is None:
            existing = await self.find_assistant_reply(
                context=context,
                conversation_id=conversation_id,
                inbound_message_id=inbound_message_id,
            )
            return _PersistedAssistant(
                message_id=existing,
                created=False,
                authority_available=True,
            )
        return _PersistedAssistant(
            message_id=cast(UUID, created_id),
            created=True,
            authority_available=True,
        )

    async def is_new_contact(
        self,
        *,
        context: TenantContext,
        conversation_id: UUID,
        inbound_message_id: UUID,
        not_before: datetime | None,
    ) -> bool:
        await set_tenant_context(self._session, context.tenant_id)
        return bool(
            await self._session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM public.conversations c "
                    "JOIN public.messages inbound ON inbound.tenant_id=c.tenant_id "
                    "AND inbound.conversation_id=c.id "
                    "WHERE c.tenant_id=:tenant AND c.id=:conversation AND inbound.id=:inbound "
                    "AND (CAST(:not_before AS timestamptz) IS NULL OR c.created_at>=:not_before) "
                    "AND NOT EXISTS (SELECT 1 FROM public.messages prior "
                    "WHERE prior.tenant_id=c.tenant_id AND prior.conversation_id=c.id "
                    "AND prior.id<>inbound.id AND prior.direction='outbound') "
                    "AND NOT EXISTS (SELECT 1 FROM public.whatsapp_history_messages history "
                    "WHERE history.tenant_id=c.tenant_id AND history.whatsapp_account_id=c.whatsapp_account_id "
                    "AND history.customer_wa_id=c.customer_wa_id) "
                    "AND NOT EXISTS (SELECT 1 FROM public.whatsapp_contacts contact "
                    "WHERE contact.tenant_id=c.tenant_id AND contact.whatsapp_account_id=c.whatsapp_account_id "
                    "AND contact.customer_wa_id=c.customer_wa_id AND NOT contact.is_deleted))"
                ),
                {
                    "tenant": context.tenant_id,
                    "conversation": conversation_id,
                    "inbound": inbound_message_id,
                    "not_before": not_before,
                },
            )
        )


def load_customer_service_core_prompt() -> str:
    path = Path(__file__).with_name("prompts") / "customer_service_core.md"
    return path.read_text(encoding="utf-8").strip()


def _turn_message(row: RowMapping) -> TurnMessage:
    content = row["content"]
    text_value: str | None = None
    if isinstance(content, Mapping):
        candidate = content.get("text")
        if isinstance(candidate, str) and candidate.strip():
            text_value = candidate
    if text_value is None:
        text_value = f"[Inbound {row['message_type']} message]"
    role: Literal["user", "assistant"] = (
        "assistant" if row["sender_type"] == "ai" else "user"
    )
    return TurnMessage(
        id=cast(UUID, row["id"]),
        role=role,
        text=text_value,
    )


def _runtime_metadata(
    *,
    agent_spec: AgentSpecSnapshot,
    result: AgentTurnResult,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "model": agent_spec.model.model,
        "reasoning_effort": agent_spec.model.reasoning_effort,
        "agent_spec_digest": agent_spec.digest,
        "usage": {
            "requests": result.usage.requests,
            "input_tokens": result.usage.input_tokens,
            "cached_input_tokens": result.usage.cached_input_tokens,
            "output_tokens": result.usage.output_tokens,
            "reasoning_tokens": result.usage.reasoning_tokens,
            "total_tokens": result.usage.total_tokens,
        },
        "tool_calls": [
            {
                "tool_name": call.tool_name,
                "arguments": dict(call.arguments),
                "output": call.output,
            }
            for call in result.tool_calls
        ],
    }
    if result.provider_response_id is not None:
        metadata["provider_response_id"] = result.provider_response_id
    json.dumps(metadata, allow_nan=False)
    return metadata
