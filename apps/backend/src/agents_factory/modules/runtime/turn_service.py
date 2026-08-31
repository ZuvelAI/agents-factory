from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
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
    state_version: int
    messages: tuple[TurnMessage, ...]
    inbound_message: TurnMessage


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

        if not self._may_ai_respond(loaded.control_state):
            await self._record_suppression(conversation_id, "before_generation")
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
        turn = AgentTurnInput(
            agent_spec=agent_spec,
            messages=loaded.messages,
            tools=selected_tools,
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
            expected_state_version=loaded.state_version,
        )
        if not persisted.authority_available:
            await self._record_suppression(conversation_id, "after_generation")
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

    async def _record_suppression(self, conversation_id: UUID, stage: str) -> None:
        await self._audit.record(
            context=self._context,
            event_type="agent.turn.authority_suppressed",
            entity_type="conversation",
            entity_id=conversation_id,
            payload={"stage": stage},
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
        state_row = (
            (
                await self._session.execute(
                    text(
                        "SELECT control_state, state_version FROM public.conversations "
                        "WHERE tenant_id = :tenant_id AND id = :conversation_id"
                    ),
                    {
                        "tenant_id": context.tenant_id,
                        "conversation_id": conversation_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if state_row is None:
            return None
        inbound_row = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, direction, sender_type, message_type, content, "
                        "arrival_sequence, (SELECT observation FROM public.media_observations o WHERE o.tenant_id=public.messages.tenant_id AND o.id=public.messages.id) AS media_observation FROM public.messages "
                        "WHERE tenant_id = :tenant_id "
                        "AND conversation_id = :conversation_id "
                        "AND id = :inbound_message_id "
                        "AND direction = 'inbound' AND sender_type = 'customer'"
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
                        "SELECT id, direction, sender_type, message_type, content, (SELECT observation FROM public.media_observations o WHERE o.tenant_id=public.messages.tenant_id AND o.id=public.messages.id) AS media_observation "
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
            control_state=ConversationControlState(state_row["control_state"]),
            state_version=state_row["state_version"],
            messages=messages,
            inbound_message=inbound,
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
        expected_state_version: int,
    ) -> _PersistedAssistant:
        await set_tenant_context(self._session, context.tenant_id)
        state_row = (
            (
                await self._session.execute(
                    text(
                        "SELECT control_state, state_version FROM public.conversations "
                        "WHERE tenant_id = :tenant_id AND id = :conversation_id "
                        "FOR UPDATE"
                    ),
                    {
                        "tenant_id": context.tenant_id,
                        "conversation_id": conversation_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if state_row is None:
            raise AgentTurnNotFound
        if state_row[
            "state_version"
        ] != expected_state_version or not ConversationStateMachine.may_ai_respond(
            state=ConversationControlState(state_row["control_state"]),
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
        runtime_metadata = _runtime_metadata(agent_spec=agent_spec, result=result)
        runtime_metadata["conversation_state_version"] = expected_state_version
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


def load_customer_service_core_prompt() -> str:
    path = Path(__file__).with_name("prompts") / "customer_service_core.md"
    return path.read_text(encoding="utf-8").strip()


def _turn_message(row: RowMapping) -> TurnMessage:
    content = row["content"]
    text_value: str | None = None
    if isinstance(content, Mapping):
        if row["message_type"] != "text" and row["sender_type"] == "customer":
            from agents_factory.modules.media.service import observation_text

            text_value = observation_text(
                {"media_observation": row.get("media_observation")}
            )
        candidate = content.get("text")
        if text_value is None and isinstance(candidate, str) and candidate.strip():
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
