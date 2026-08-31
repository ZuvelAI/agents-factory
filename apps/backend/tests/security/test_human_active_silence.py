from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.conversations.service import ConversationService


async def _seed_handoff_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, tuple[UUID, UUID]]:
    tenant_id = new_uuid7()
    account_id = new_uuid7()
    event_ids = (new_uuid7(), new_uuid7())
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:id, :slug, 'Handoff Tenant', 'active')"
            ),
            {"id": tenant_id, "slug": f"handoff-{tenant_id.hex}"},
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
            ":provider_id, '573000000002', 'text', :occurred_at, "
            ":raw_payload, :content)"
        ).bindparams(
            bindparam("raw_payload", type_=JSONB),
            bindparam("content", type_=JSONB),
        )
        for index, event_id in enumerate(event_ids):
            await session.execute(
                statement,
                {
                    "id": event_id,
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "provider_id": f"wamid.handoff.{index}",
                    "occurred_at": datetime(2026, 8, 27, tzinfo=UTC)
                    + timedelta(seconds=index),
                    "raw_payload": {"fixture": index},
                    "content": {"text": f"handoff-{index}"},
                },
            )
    return tenant_id, event_ids


def _context(tenant_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=new_uuid7(),
    )


@pytest.mark.asyncio
async def test_human_active_persists_but_never_queues_or_allows_ai(
    conversation_session_factory: async_sessionmaker[AsyncSession],
    clean_conversation_tables: None,
) -> None:
    _ = clean_conversation_tables
    session_factory = conversation_session_factory
    tenant_id, event_ids = await _seed_handoff_events(session_factory)
    context = _context(tenant_id)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )
        first = await service.ingest(event_ids[0])
    from apps.backend.tests.handoff_support import activate_verified_handoff

    await activate_verified_handoff(session_factory, context, first.conversation_id)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )
        assert await service.may_ai_respond(first.conversation_id) is False
        human_owned = await service.ingest(event_ids[1])
        duplicate = await service.ingest(event_ids[1])

    assert human_owned.message_created is True
    assert human_owned.response_queued is False
    assert duplicate.message_created is False
    assert duplicate.response_queued is False

    async with session_factory.begin() as session:
        message_count = await session.scalar(
            text("SELECT count(*) FROM public.messages")
        )
        response_jobs = await session.scalar(
            text("SELECT count(*) FROM public.outbox_jobs WHERE topic = 'agent.turn'")
        )
        attempt_count = await session.scalar(
            text(
                "SELECT count(*) FROM public.job_attempts AS attempt "
                "JOIN public.outbox_jobs AS job ON job.id = attempt.outbox_job_id "
                "WHERE job.topic = 'agent.turn'"
            )
        )
        audit_messages = await session.scalar(
            text(
                "SELECT count(*) FROM public.audit_events "
                "WHERE event_type = 'conversation.message.received'"
            )
        )
    assert message_count == 3  # Includes the deterministic handoff waiting receipt.
    assert response_jobs == 1
    assert attempt_count == 0
    assert audit_messages == 2

    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            await session.execute(
                text(
                    "UPDATE public.conversations SET control_state = 'AI_ACTIVE' "
                    "WHERE id = :conversation_id"
                ),
                {"conversation_id": first.conversation_id},
            )
