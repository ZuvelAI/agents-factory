from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from redis.asyncio import Redis

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import (
    JobEnvelope,
    JobHandler,
    configure_durable_worker,
)
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.handoffs.service import HandoffService
from agents_factory.modules.handoffs.surfaces import HumanSurfaceRegistry
from agents_factory.modules.media.contracts import MediaProcessor
from agents_factory.modules.runtime.contracts import AgentRuntime
from agents_factory.modules.runtime.openai_adapter import OpenAIAgentsRuntime
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.runtime.turn_service import (
    AgentSpecProvider,
    AgentTurnService,
    Milestone2AgentSpecProvider,
)
from agents_factory.modules.usage.recorder import UsageRecorder
from agents_factory.modules.usage.runtime import MeteredAgentRuntime
from agents_factory.modules.usage.capacity import UsageCapacity
from agent_worker.approval_jobs import configure_approval_execution


class InvalidAgentTurnJob(ValueError):
    pass


async def configure_agent_worker(context: dict[Any, Any]) -> None:
    await configure_durable_worker(context)
    database = cast(Database, context["database"])
    capacity = UsageCapacity(cast(Redis, context["redis"]))
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
    media = cast(MediaProcessor | None, context.get("media_processor"))
    handoffs = cast(
        HandoffService,
        context.get("handoff_service")
        or HandoffService(database.session_factory, surfaces=HumanSurfaceRegistry()),
    )

    async def agent_turn_handler(envelope: JobEnvelope) -> None:
        await handle_agent_turn(
            envelope=envelope,
            database=database,
            runtime=runtime,
            agent_specs=agent_specs,
            tools=tools,
            media=media,
            handoffs=handoffs,
            capacity=capacity,
        )

    async def whatsapp_inbound_handler(envelope: JobEnvelope) -> None:
        await handle_whatsapp_inbound(envelope=envelope, database=database, media=media)

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers["whatsapp.inbound.received"] = whatsapp_inbound_handler
    handlers["agent.turn"] = agent_turn_handler
    configure_approval_execution(context)


async def handle_whatsapp_inbound(
    *,
    envelope: JobEnvelope,
    database: Database,
    media: MediaProcessor | None = None,
) -> None:
    if envelope.kind != "whatsapp.inbound.received":
        raise InvalidAgentTurnJob("unexpected inbound job kind")
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        context = TenantContext(
            tenant_id=envelope.tenant_id,
            actor_id=envelope.job_id,
            actor_type="system",
            correlation_id=envelope.job_id,
        )
        ingested = await ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(envelope.aggregate_id)
    # Preserve evidence even under human takeover. The committed inbound remains
    # replayable if normalization fails; do not hold its transaction over I/O.
    if media is not None:
        await media.process(context=context, message_id=ingested.message_id)


async def handle_agent_turn(
    *,
    envelope: JobEnvelope,
    database: Database,
    runtime: AgentRuntime,
    agent_specs: AgentSpecProvider,
    tools: RuntimeToolRegistry,
    media: MediaProcessor | None = None,
    handoffs: HandoffService | None = None,
    capacity: UsageCapacity | None = None,
) -> None:
    if envelope.kind != "agent.turn":
        raise InvalidAgentTurnJob("unexpected job kind")
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        job = (
            (
                await session.execute(
                    text(
                        "SELECT payload, attempt_count-deferral_count AS attempt_count "
                        "FROM public.outbox_jobs WHERE tenant_id = :tenant_id AND id = :job_id"
                    ),
                    {"tenant_id": envelope.tenant_id, "job_id": envelope.job_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        conversation_id, inbound_message_id = _parse_payload(
            job["payload"] if job is not None else None,
            expected_conversation_id=envelope.aggregate_id,
        )
        context = TenantContext(
            tenant_id=envelope.tenant_id,
            actor_id=envelope.job_id,
            actor_type="system",
            correlation_id=envelope.job_id,
        )
        # This may race inbound normalization; MediaService serializes the same
        # provider object and reuses its durable observation without a second call.
        if media is not None:
            await media.process(context=context, message_id=inbound_message_id)
        if handoffs is not None:
            await handoffs.inspect_inbound(
                context=context,
                conversation_id=conversation_id,
                message_id=inbound_message_id,
            )
        await AgentTurnService(
            session=session,
            context=context,
            runtime=MeteredAgentRuntime(
                runtime,
                UsageRecorder(database.session_factory),
                attempt_number=max(1, job["attempt_count"]) if job is not None else 1,
                capacity=capacity,
            ),
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
