from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from agents_factory.config import load_settings
from agent_worker.publication_jobs import handle_publication_test

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import (
    JobEnvelope,
    JobHandler,
    configure_durable_worker,
)
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.agent_factory.channel_provider import (
    ConversationAgentSpecProvider,
)
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.runtime.contracts import AgentRuntime
from agents_factory.modules.runtime.openai_adapter import OpenAIAgentsRuntime
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.runtime.turn_service import (
    AgentSpecProvider,
    AgentTurnService,
    Milestone2AgentSpecProvider,
)
from agents_factory.modules.whatsapp.history_sync import import_history_inbox


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

    async def whatsapp_history_handler(envelope: JobEnvelope) -> None:
        await handle_whatsapp_history_import(envelope=envelope, database=database)

    async def publication_test_handler(envelope: JobEnvelope) -> None:
        await handle_publication_test(
            envelope=envelope,
            database=database,
            runtime=runtime,
            code_digest=load_settings().agent_publication_code_digest,
        )

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers["whatsapp.inbound.received"] = whatsapp_inbound_handler
    handlers["whatsapp.history.import"] = whatsapp_history_handler
    handlers["agent.turn"] = agent_turn_handler
    handlers["agent.publication.test"] = publication_test_handler


async def handle_whatsapp_history_import(
    *,
    envelope: JobEnvelope,
    database: Database,
) -> None:
    if envelope.kind != "whatsapp.history.import":
        raise InvalidAgentTurnJob("unexpected history import job kind")
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        payload = await session.scalar(
            text(
                "SELECT payload FROM public.outbox_jobs "
                "WHERE tenant_id=:tenant AND id=:job AND topic='whatsapp.history.import'"
            ),
            {"tenant": envelope.tenant_id, "job": envelope.job_id},
        )
        if not isinstance(payload, Mapping):
            raise InvalidAgentTurnJob("history import payload is unavailable")
        try:
            inbox_id = UUID(str(payload["inbox_id"]))
            account_id = UUID(str(payload["whatsapp_account_id"]))
        except (KeyError, TypeError, ValueError):
            raise InvalidAgentTurnJob("history import payload is invalid") from None
        if inbox_id != envelope.aggregate_id or str(inbox_id) != payload.get(
            "aggregate_id"
        ):
            raise InvalidAgentTurnJob("history import aggregate does not match payload")
        actual_account = await session.scalar(
            text(
                "SELECT whatsapp_account_id FROM public.whatsapp_history_inbox "
                "WHERE tenant_id=:tenant AND id=:inbox"
            ),
            {"tenant": envelope.tenant_id, "inbox": inbox_id},
        )
        if actual_account != account_id:
            raise InvalidAgentTurnJob("history import account does not match inbox")
        context = TenantContext(
            tenant_id=envelope.tenant_id,
            actor_id=None,
            actor_type="system",
            correlation_id=envelope.job_id,
        )
        await import_history_inbox(session, context=context, inbox_id=inbox_id)
        # Media-only batches may have arrived before their archived placeholder.
        # Revisit only batches whose every media ID is now in this account's
        # archive. Receipts make repeat deliveries harmless.
        while True:
            ready = (
                (
                    await session.execute(
                        text(
                            "SELECT inbox.id FROM public.whatsapp_history_inbox AS inbox "
                            "WHERE inbox.tenant_id=:tenant AND inbox.whatsapp_account_id=:account "
                            "AND jsonb_array_length(inbox.payload->'media_messages') > 0 "
                            "AND NOT EXISTS (SELECT 1 FROM public.whatsapp_history_import_receipts AS receipt "
                            "WHERE receipt.tenant_id=inbox.tenant_id AND receipt.inbox_id=inbox.id) "
                            "AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(inbox.payload->'media_messages') AS media "
                            "WHERE NOT EXISTS (SELECT 1 FROM public.whatsapp_history_messages AS message "
                            "WHERE message.tenant_id=inbox.tenant_id "
                            "AND message.whatsapp_account_id=inbox.whatsapp_account_id "
                            "AND message.provider_message_id=media->>'id')) "
                            "ORDER BY inbox.received_at,inbox.id LIMIT 100"
                        ),
                        {"tenant": envelope.tenant_id, "account": account_id},
                    )
                )
                .scalars()
                .all()
            )
            if not ready:
                break
            for pending_id in ready:
                await import_history_inbox(
                    session, context=context, inbox_id=pending_id
                )


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
            agent_specs=(
                ConversationAgentSpecProvider(
                    session,
                    context,
                    conversation_id,
                    agent_specs,
                    code_digest=load_settings().agent_publication_code_digest,
                    compatible_versions=load_settings().agent_publication_compatible_versions,
                )
                if isinstance(agent_specs, Milestone2AgentSpecProvider)
                else agent_specs
            ),
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
