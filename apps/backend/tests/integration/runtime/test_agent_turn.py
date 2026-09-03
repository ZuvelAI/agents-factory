from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.runtime.contracts import (
    AgentRuntime,
    AgentSpecSnapshot,
    AgentTurnInput,
    AgentTurnResult,
    ModelConfiguration,
    RuntimeLimits,
    RuntimeUsage,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry
from agents_factory.modules.runtime.turn_service import (
    AgentSpecProvider,
    AgentTurnService,
)


@dataclass
class _FakeRuntime(AgentRuntime):
    turns: list[AgentTurnInput] = field(default_factory=list)

    async def run(self, turn: AgentTurnInput) -> AgentTurnResult:
        self.turns.append(turn)
        return AgentTurnResult(
            output_text="Hola, ya reviso tu solicitud.",
            tool_calls=(),
            usage=RuntimeUsage(
                requests=1,
                input_tokens=10,
                cached_input_tokens=0,
                output_tokens=8,
                reasoning_tokens=2,
                total_tokens=18,
            ),
            provider_response_id="fake-response-1",
        )


@dataclass(frozen=True)
class _SpecProvider(AgentSpecProvider):
    spec: AgentSpecSnapshot

    async def get_active(self, *, tenant_id: UUID) -> AgentSpecSnapshot | None:
        assert tenant_id == self.spec.tenant_id
        return self.spec


def _context(tenant_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=new_uuid7(),
    )


def _spec(tenant_id: UUID, *, active: bool = True) -> AgentSpecSnapshot:
    return AgentSpecSnapshot(
        id=new_uuid7(),
        tenant_id=tenant_id,
        version="integration-v1",
        digest="c" * 64,
        product="customer_service",
        product_version="1.0.0",
        instructions="Respond to the customer.",
        active_capabilities=frozenset(),
        permitted_tools=frozenset(),
        model=ModelConfiguration(),
        limits=RuntimeLimits(),
        active=active,
    )


async def _seed_inbound(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[TenantContext, UUID, UUID]:
    tenant_id = new_uuid7()
    account_id = new_uuid7()
    event_id = new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:id, :slug, 'Runtime Tenant', 'active')"
            ),
            {"id": tenant_id, "slug": f"runtime-{tenant_id.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, status) "
                "VALUES (:id, :tenant_id, 'meta', :waba, :phone, 'active')"
            ),
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "waba": f"waba-{tenant_id.hex}",
                "phone": f"phone-{tenant_id.hex}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_webhook_events "
                "(id, tenant_id, whatsapp_account_id, whatsapp_message_id, "
                "sender_wa_id, message_type, provider_timestamp, raw_payload, "
                "normalized_content) VALUES (:id, :tenant_id, :account_id, "
                ":message_id, '573000000003', 'text', :occurred_at, "
                ":payload, :content)"
            ).bindparams(
                bindparam("payload", type_=JSONB),
                bindparam("content", type_=JSONB),
            ),
            {
                "id": event_id,
                "tenant_id": tenant_id,
                "account_id": account_id,
                "message_id": f"wamid.runtime.{event_id}",
                "occurred_at": datetime(2026, 8, 27, tzinfo=UTC),
                "payload": {"fixture": "runtime"},
                "content": {"text": "Necesito ayuda"},
            },
        )
    context = _context(tenant_id)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        ingested = await ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        ).ingest(event_id)
    return context, ingested.conversation_id, ingested.message_id


@pytest.mark.asyncio
async def test_turn_persists_assistant_result_before_outbound_intent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context, conversation_id, inbound_message_id = await _seed_inbound(session_factory)
    runtime = _FakeRuntime()
    provider = _SpecProvider(_spec(context.tenant_id))

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = AgentTurnService(
            session=session,
            context=context,
            runtime=runtime,
            agent_specs=provider,
            tools=RuntimeToolRegistry(()),
        )
        completed = await service.process(
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
        )
        replayed = await service.process(
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
        )

    assert completed.status == "completed"
    assert completed.assistant_message_id is not None
    assert replayed.status == "already_processed"
    assert replayed.assistant_message_id == completed.assistant_message_id
    assert len(runtime.turns) == 1
    assert runtime.turns[0].agent_spec is provider.spec
    assert runtime.turns[0].messages[-1].text == "Necesito ayuda"

    async with session_factory.begin() as session:
        response = (
            (
                await session.execute(
                    text(
                        "SELECT content, agent_spec_id, agent_spec_version, "
                        "runtime_metadata FROM public.messages "
                        "WHERE id = :message_id"
                    ),
                    {"message_id": completed.assistant_message_id},
                )
            )
            .mappings()
            .one()
        )
        outbound_jobs = await session.scalar(
            text(
                "SELECT count(*) FROM public.outbox_jobs WHERE topic = 'outbound.text'"
            )
        )

    assert response["content"] == {"text": "Hola, ya reviso tu solicitud."}
    assert response["agent_spec_id"] == provider.spec.id
    assert response["agent_spec_version"] == provider.spec.version
    assert response["runtime_metadata"]["usage"]["total_tokens"] == 18
    assert outbound_jobs == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["human_active", "inactive_spec"])
async def test_turn_short_circuits_before_runtime_when_authority_is_absent(
    session_factory: async_sessionmaker[AsyncSession],
    blocker: str,
) -> None:
    context, conversation_id, inbound_message_id = await _seed_inbound(session_factory)
    runtime = _FakeRuntime()
    spec = _spec(context.tenant_id)

    if blocker == "human_active":
        from apps.backend.tests.handoff_support import activate_verified_handoff

        await activate_verified_handoff(session_factory, context, conversation_id)
    else:
        spec = replace(spec, active=False)

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        result = await AgentTurnService(
            session=session,
            context=context,
            runtime=runtime,
            agent_specs=_SpecProvider(spec),
            tools=RuntimeToolRegistry(()),
        ).process(
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
        )

    assert result.status == (
        "blocked_by_conversation_control"
        if blocker == "human_active"
        else "inactive_agent_spec"
    )
    assert runtime.turns == []
