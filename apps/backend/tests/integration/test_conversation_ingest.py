from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.conversations.models import (
    AwaitingHumanPolicy,
    ConversationControlState,
)
from agents_factory.modules.conversations.service import ConversationService


@dataclass(frozen=True, slots=True)
class _ConversationWorld:
    tenant_id: UUID
    account_id: UUID
    event_ids: tuple[UUID, ...]


async def _seed_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider_offsets: tuple[int, ...],
) -> _ConversationWorld:
    tenant_id = new_uuid7()
    account_id = new_uuid7()
    event_ids = tuple(new_uuid7() for _ in provider_offsets)
    base_time = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:tenant_id, :slug, 'Conversation Tenant', 'active')"
            ),
            {"tenant_id": tenant_id, "slug": f"conversation-{tenant_id.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, status) "
                "VALUES (:id, :tenant_id, 'meta', :waba_id, :phone_id, 'active')"
            ),
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "waba_id": f"waba-{tenant_id.hex}",
                "phone_id": f"phone-{tenant_id.hex}",
            },
        )
        statement = text(
            "INSERT INTO public.whatsapp_webhook_events "
            "(id, tenant_id, whatsapp_account_id, whatsapp_message_id, "
            "sender_wa_id, message_type, provider_timestamp, raw_payload, "
            "normalized_content) VALUES (:id, :tenant_id, :account_id, "
            ":message_id, '573000000001', 'text', :provider_timestamp, "
            ":raw_payload, :content)"
        ).bindparams(
            bindparam("raw_payload", type_=JSONB),
            bindparam("content", type_=JSONB),
        )
        for index, (event_id, offset) in enumerate(
            zip(event_ids, provider_offsets, strict=True),
            start=1,
        ):
            await session.execute(
                statement,
                {
                    "id": event_id,
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "message_id": f"wamid.conversation.{index}",
                    "provider_timestamp": base_time + timedelta(seconds=offset),
                    "raw_payload": {"fixture": index},
                    "content": {"text": f"message-{index}"},
                },
            )
    return _ConversationWorld(
        tenant_id=tenant_id,
        account_id=account_id,
        event_ids=event_ids,
    )


def _context(tenant_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=new_uuid7(),
    )


@pytest.mark.asyncio
async def test_ingest_is_idempotent_and_orders_by_provider_time_then_arrival(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    world = await _seed_events(session_factory, provider_offsets=(60, 0))
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = ConversationService(
            session=session,
            context=_context(world.tenant_id),
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )
        first = await service.ingest(world.event_ids[0])
        duplicate = await service.ingest(world.event_ids[0])
        delayed = await service.ingest(world.event_ids[1])

    assert first.message_created is True
    assert first.response_queued is True
    assert duplicate.message_id == first.message_id
    assert duplicate.message_created is False
    assert duplicate.response_queued is False
    assert delayed.conversation_id == first.conversation_id

    async with session_factory.begin() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT source_event_id, arrival_sequence "
                    "FROM public.messages ORDER BY provider_timestamp, "
                    "arrival_sequence"
                )
            )
        ).all()
        arrival_rows = (
            await session.execute(
                text(
                    "SELECT source_event_id, arrival_sequence "
                    "FROM public.messages ORDER BY arrival_sequence"
                )
            )
        ).all()
        state_events = (
            await session.execute(
                text(
                    "SELECT from_state, to_state, version, actor_type, reason "
                    "FROM public.conversation_state_events ORDER BY version"
                )
            )
        ).all()
        response_jobs = await session.scalar(
            text("SELECT count(*) FROM public.outbox_jobs WHERE topic = 'agent.turn'")
        )
        audit_messages = await session.scalar(
            text(
                "SELECT count(*) FROM public.audit_events "
                "WHERE event_type = 'conversation.message.received'"
            )
        )

    assert [row.source_event_id for row in rows] == [
        world.event_ids[1],
        world.event_ids[0],
    ]
    assert [row.source_event_id for row in arrival_rows] == list(world.event_ids)
    assert [row.arrival_sequence for row in arrival_rows] == [1, 2]
    assert [tuple(row) for row in state_events] == [
        (None, "AI_ACTIVE", 1, "system", "inbound_opened")
    ]
    assert response_jobs == 2
    assert audit_messages == 2


@pytest.mark.asyncio
async def test_closed_conversation_reopens_only_when_policy_allows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    world = await _seed_events(session_factory, provider_offsets=(0, 1, 2))
    context = _context(world.tenant_id)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )
        opened = await service.ingest(world.event_ids[0])
        await service.close_conversation(
            conversation_id=opened.conversation_id,
            reason="session_complete",
        )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        closed_service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
            reopen_closed_on_inbound=False,
        )
        remained_closed = await closed_service.ingest(world.event_ids[1])

    assert remained_closed.control_state == ConversationControlState.CLOSED
    assert remained_closed.message_created is True
    assert remained_closed.response_queued is False

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        reopen_service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
            reopen_closed_on_inbound=True,
        )
        reopened = await reopen_service.ingest(world.event_ids[2])

    assert reopened.control_state == ConversationControlState.AI_ACTIVE
    assert reopened.response_queued is True
    async with session_factory.begin() as session:
        states = (
            await session.execute(
                text(
                    "SELECT to_state, version, reason "
                    "FROM public.conversation_state_events ORDER BY version"
                )
            )
        ).all()
    assert [tuple(row) for row in states] == [
        ("AI_ACTIVE", 1, "inbound_opened"),
        ("CLOSED", 2, "session_complete"),
        ("AI_ACTIVE", 3, "inbound_reopened"),
    ]
