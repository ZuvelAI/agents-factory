from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import (
    JobEnvelope,
    JobHandler,
    configure_durable_worker,
)
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.runtime.contracts import AgentRuntime
from agents_factory.modules.runtime.openai_adapter import OpenAIAgentsRuntime
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.runtime.turn_service import (
    AgentSpecProvider,
    AgentTurnService,
    Milestone2AgentSpecProvider,
)


class InvalidAgentTurnJob(ValueError):
    pass


async def configure_agent_worker(context: dict[Any, Any]) -> None:
    await configure_durable_worker(context)
    database = cast(Database, context["database"])
    runtime = cast(
        AgentRuntime,
        context.get("agent_runtime") or OpenAIAgentsRuntime(),
    )
    agent_specs = cast(
        AgentSpecProvider,
        context.get("agent_spec_provider") or Milestone2AgentSpecProvider(),
    )
    tools = cast(
        RuntimeToolRegistry,
        context.get("runtime_tool_registry") or RuntimeToolRegistry(()),
    )

    async def agent_turn_handler(envelope: JobEnvelope) -> None:
        await handle_agent_turn(
            envelope=envelope,
            database=database,
            runtime=runtime,
            agent_specs=agent_specs,
            tools=tools,
        )

    async def whatsapp_inbound_handler(envelope: JobEnvelope) -> None:
        await handle_whatsapp_inbound(envelope=envelope, database=database)

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers["whatsapp.inbound.received"] = whatsapp_inbound_handler
    handlers["agent.turn"] = agent_turn_handler


async def handle_whatsapp_inbound(
    *,
    envelope: JobEnvelope,
    database: Database,
) -> None:
    if envelope.kind != "whatsapp.inbound.received":
        raise InvalidAgentTurnJob("unexpected inbound job kind")
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        context = TenantContext(
            tenant_id=envelope.tenant_id,
            actor_id=None,
            actor_type="system",
            correlation_id=envelope.job_id,
        )
        await ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(envelope.aggregate_id)


async def handle_agent_turn(
    *,
    envelope: JobEnvelope,
    database: Database,
    runtime: AgentRuntime,
    agent_specs: AgentSpecProvider,
    tools: RuntimeToolRegistry,
) -> None:
    if envelope.kind != "agent.turn":
        raise InvalidAgentTurnJob("unexpected job kind")
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        payload = await session.scalar(
            text(
                "SELECT payload FROM public.outbox_jobs "
                "WHERE tenant_id = :tenant_id AND id = :job_id"
            ),
            {"tenant_id": envelope.tenant_id, "job_id": envelope.job_id},
        )
        conversation_id, inbound_message_id = _parse_payload(
            payload,
            expected_conversation_id=envelope.aggregate_id,
        )
        context = TenantContext(
            tenant_id=envelope.tenant_id,
            actor_id=None,
            actor_type="system",
            correlation_id=envelope.job_id,
        )
        await AgentTurnService(
            session=session,
            context=context,
            runtime=runtime,
            agent_specs=agent_specs,
            tools=tools,
        ).process(
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
        )


def _parse_payload(
    value: object,
    *,
    expected_conversation_id: UUID,
) -> tuple[UUID, UUID]:
    if not isinstance(value, Mapping):
        raise InvalidAgentTurnJob("agent turn payload is unavailable")
    try:
        conversation_id = UUID(str(value["conversation_id"]))
        inbound_message_id = UUID(str(value["inbound_message_id"]))
    except (KeyError, TypeError, ValueError):
        raise InvalidAgentTurnJob("agent turn payload is invalid") from None
    if conversation_id != expected_conversation_id:
        raise InvalidAgentTurnJob("agent turn aggregate does not match payload")
    return conversation_id, inbound_message_id
