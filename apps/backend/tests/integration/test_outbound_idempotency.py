from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.backend.tests.handoff_support import activate_verified_handoff
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.whatsapp.contracts import (
    OutboundTemplateRequest,
    OutboundTextRequest,
    ProviderMessageResult,
    WhatsAppDeliveryStatusEvent,
)
from agents_factory.modules.whatsapp.outbound_service import (
    OutboundMessageService,
    OutboundStatusReconciler,
)


class RecordingProvider:
    def __init__(self, results: Sequence[ProviderMessageResult]) -> None:
        self._results = list(results)
        self.text_requests: list[OutboundTextRequest] = []

    async def send_text(self, request: OutboundTextRequest) -> ProviderMessageResult:
        self.text_requests.append(request)
        return self._results.pop(0)

    async def send_template(
        self,
        request: OutboundTemplateRequest,
    ) -> ProviderMessageResult:
        raise AssertionError(f"unexpected template send: {request}")


def _context(tenant_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=new_uuid7(),
    )


async def _seed_text_reply(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    inbound_at: datetime | None = None,
) -> tuple[UUID, UUID, UUID, UUID]:
    tenant_id = new_uuid7()
    account_id = new_uuid7()
    conversation_id = new_uuid7()
    inbound_id = new_uuid7()
    assistant_id = new_uuid7()
    agent_spec_id = new_uuid7()
    occurred_at = inbound_at or datetime.now(UTC)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) VALUES "
                "(:id, :slug, 'Outbound Tenant', 'active')"
            ),
            {"id": tenant_id, "slug": f"outbound-{tenant_id.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, status) "
                "VALUES (:id, :tenant_id, 'meta', :waba_id, :phone_number_id, "
                "'active')"
            ),
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "waba_id": f"waba-{account_id.hex}",
                "phone_number_id": f"phone-{account_id.hex}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations "
                "(id, tenant_id, whatsapp_account_id, customer_wa_id) "
                "VALUES (:id, :tenant_id, :account_id, '573000000001')"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "account_id": account_id,
            },
        )
        insert_message = text(
            "INSERT INTO public.messages "
            "(id, tenant_id, conversation_id, in_reply_to_message_id, direction, "
            "sender_type, provider_message_id, message_type, content, "
            "provider_timestamp, arrival_sequence, agent_spec_id, "
            "agent_spec_version) VALUES "
            "(:id, :tenant_id, :conversation_id, :reply_to, :direction, "
            ":sender_type, :provider_message_id, 'text', :content, "
            ":provider_timestamp, :arrival_sequence, :agent_spec_id, "
            ":agent_spec_version)"
        ).bindparams(bindparam("content", type_=JSONB))
        await session.execute(
            insert_message,
            {
                "id": inbound_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "reply_to": None,
                "direction": "inbound",
                "sender_type": "customer",
                "provider_message_id": f"wamid.inbound.{inbound_id}",
                "content": {"text": "Hola"},
                "provider_timestamp": occurred_at,
                "arrival_sequence": 1,
                "agent_spec_id": None,
                "agent_spec_version": None,
            },
        )
        await session.execute(
            insert_message,
            {
                "id": assistant_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "reply_to": inbound_id,
                "direction": "outbound",
                "sender_type": "ai",
                "provider_message_id": None,
                "content": {"text": "Hola, ¿cómo puedo ayudarte?"},
                "provider_timestamp": occurred_at + timedelta(seconds=1),
                "arrival_sequence": 2,
                "agent_spec_id": agent_spec_id,
                "agent_spec_version": "m2-test",
            },
        )
    return tenant_id, account_id, conversation_id, assistant_id


@pytest.mark.asyncio
async def test_duplicate_prepare_and_send_produce_one_customer_message(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, _, _, assistant_id = await _seed_text_reply(session_factory)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="wamid.out.1")]
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant_id),
        provider=provider,
    )

    first_id = await service.prepare_text(message_id=assistant_id)
    duplicate_id = await service.prepare_text(message_id=assistant_id)
    first_send = await service.send(first_id)
    duplicate_send = await service.send(first_id)

    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status, provider_message_id, attempt_count, "
                        "status_history FROM public.outbound_messages"
                    )
                )
            )
            .mappings()
            .one()
        )
        send_jobs = await session.scalar(
            text(
                "SELECT count(*) FROM public.outbox_jobs "
                "WHERE topic = 'whatsapp.outbound.send'"
            )
        )

    assert duplicate_id == first_id
    assert first_send.status == "ACCEPTED"
    assert duplicate_send.status == "ACCEPTED"
    assert len(provider.text_requests) == 1
    assert row["provider_message_id"] == "wamid.out.1"
    assert row["attempt_count"] == 1
    assert [entry["status"] for entry in row["status_history"]] == [
        "PREPARED",
        "SENDING",
        "ACCEPTED",
    ]
    assert send_jobs == 1


@pytest.mark.asyncio
async def test_ambiguous_timeout_is_not_blindly_retried(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, _, _, assistant_id = await _seed_text_reply(session_factory)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="uncertain", error_code="provider_timeout")]
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant_id),
        provider=provider,
    )
    outbound_id = await service.prepare_text(message_id=assistant_id)

    first = await service.send(outbound_id)
    replay = await service.send(outbound_id)

    assert first.status == "UNCERTAIN"
    assert replay.status == "UNCERTAIN"
    assert len(provider.text_requests) == 1


@pytest.mark.asyncio
async def test_provider_rejection_is_persisted_without_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, _, _, assistant_id = await _seed_text_reply(session_factory)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="rejected", error_code="meta_131047")]
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant_id),
        provider=provider,
    )
    outbound_id = await service.prepare_text(message_id=assistant_id)

    rejected = await service.send(outbound_id)
    replay = await service.send(outbound_id)

    assert rejected.status == "FAILED"
    assert replay.status == "FAILED"
    assert rejected.error_code == "meta_131047"
    assert len(provider.text_requests) == 1


@pytest.mark.asyncio
async def test_send_rechecks_conversation_authority(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, _, conversation_id, assistant_id = await _seed_text_reply(
        session_factory
    )
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="wamid.never")]
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant_id),
        provider=provider,
    )
    outbound_id = await service.prepare_text(message_id=assistant_id)
    await activate_verified_handoff(
        session_factory, _context(tenant_id), conversation_id
    )

    result = await service.send(outbound_id)

    assert result.status == "BLOCKED"
    assert result.error_code == "conversation_authority_unavailable"
    assert provider.text_requests == []


@pytest.mark.asyncio
async def test_delivery_callbacks_preserve_history_and_cost_attribution(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, account_id, _, assistant_id = await _seed_text_reply(session_factory)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="wamid.out.2")]
    )
    context = _context(tenant_id)
    service = OutboundMessageService(
        session_factory=session_factory,
        context=context,
        provider=provider,
    )
    outbound_id = await service.prepare_text(message_id=assistant_id)
    await service.send(outbound_id)

    occurred_at = datetime.now(UTC)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        reconciler = OutboundStatusReconciler(session)
        for offset, status in enumerate(("delivered", "read", "failed")):
            reconciled = await reconciler.reconcile(
                context=context,
                whatsapp_account_id=account_id,
                event=WhatsAppDeliveryStatusEvent(
                    waba_id="waba-test",
                    phone_number_id="phone-test",
                    whatsapp_message_id="wamid.out.2",
                    recipient_wa_id="573000000001",
                    status=status,
                    occurred_at=occurred_at + timedelta(seconds=offset),
                    raw_payload={},
                    error_code="meta_131026" if status == "failed" else None,
                    cost_attribution={
                        "billable": True,
                        "category": "service",
                        "pricing_model": "CBP",
                    }
                    if status == "delivered"
                    else {},
                ),
            )
            assert reconciled is True

    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status, status_history, cost_attribution, "
                        "provider_error_code FROM public.outbound_messages "
                        "WHERE id = :id"
                    ),
                    {"id": outbound_id},
                )
            )
            .mappings()
            .one()
        )

    assert row["status"] == "READ"
    assert [entry["status"] for entry in row["status_history"]][-3:] == [
        "DELIVERED",
        "READ",
        "FAILED",
    ]
    assert row["cost_attribution"] == {
        "billable": True,
        "category": "service",
        "pricing_model": "CBP",
    }
    assert row["provider_error_code"] == "meta_131026"
