import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import text

from apps.backend.tests.integration.test_outbound_idempotency import (
    RecordingProvider,
    _seed_text_reply,
)
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.usage.recorder import UsageRecorder
from agents_factory.modules.whatsapp.contracts import (
    OutboundTextRequest,
    ProviderMessageResult,
)
from agents_factory.modules.whatsapp.outbound_service import OutboundMessageService


class CancelAfterDispatchProvider(RecordingProvider):
    async def send_text(self, request: OutboundTextRequest) -> ProviderMessageResult:
        self.text_requests.append(request)
        raise asyncio.CancelledError


async def test_outbound_result_and_usage_are_committed_once_together(session_factory):
    tenant_id, _, conversation_id, assistant_id = await _seed_text_reply(
        session_factory
    )
    job_id = new_uuid7()
    context = TenantContext(
        tenant_id=tenant_id,
        actor_id=job_id,
        actor_type="system",
        correlation_id=job_id,
    )
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="wamid.usage.1")]
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=context,
        provider=provider,
        usage_recorder=UsageRecorder(session_factory),
    )

    outbound_id = await service.prepare_text(message_id=assistant_id)
    first = await service.send(outbound_id)
    replay = await service.send(outbound_id)

    assert first.status == replay.status == "ACCEPTED"
    assert len(provider.text_requests) == 1
    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT usage.source_key,usage.conversation_id,usage.run_id,"
                        "usage.event,usage.quote,outbound.status "
                        "FROM public.usage_records usage "
                        "JOIN public.outbound_messages outbound "
                        "ON outbound.tenant_id=usage.tenant_id "
                        "AND outbound.id=:outbound "
                        "WHERE usage.tenant_id=:tenant AND usage.kind='whatsapp'"
                    ),
                    {"tenant": tenant_id, "outbound": outbound_id},
                )
            )
            .mappings()
            .one()
        )

    assert row["source_key"] == f"whatsapp:outbound:{outbound_id}:1"
    assert row["conversation_id"] == conversation_id
    assert row["run_id"] == job_id
    assert row["status"] == "ACCEPTED"
    assert row["event"]["provider"] == "meta"
    assert row["event"]["product"] == "whatsapp_cloud_api.text"
    assert row["event"]["measurements"]["requests"] == 1
    assert row["event"]["measurements"]["messages"] == 1
    assert Decimal(row["event"]["measurements"]["latency_ms"]) >= 0
    assert row["quote"]["basis"] == "unknown"


async def test_abandoned_provider_attempt_is_reconciled_without_resend(session_factory):
    tenant_id, _, _, assistant_id = await _seed_text_reply(session_factory)
    job_id = new_uuid7()
    context = TenantContext(
        tenant_id=tenant_id,
        actor_id=job_id,
        actor_type="system",
        correlation_id=job_id,
    )
    interrupted_provider = CancelAfterDispatchProvider([])
    recorder = UsageRecorder(session_factory)
    interrupted = OutboundMessageService(
        session_factory=session_factory,
        context=context,
        provider=interrupted_provider,
        usage_recorder=recorder,
    )
    outbound_id = await interrupted.prepare_text(message_id=assistant_id)

    with pytest.raises(asyncio.CancelledError):
        await interrupted.send(outbound_id)

    replay_provider = RecordingProvider([])
    recovered = OutboundMessageService(
        session_factory=session_factory,
        context=context,
        provider=replay_provider,
        usage_recorder=recorder,
    )
    result = await recovered.send(outbound_id)
    replay = await recovered.send(outbound_id)

    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT outbound.status,outbound.provider_error_code,"
                        "outbound.attempt_count,usage.event,usage.quote "
                        "FROM public.outbound_messages outbound "
                        "JOIN public.usage_records usage "
                        "ON usage.tenant_id=outbound.tenant_id "
                        "AND usage.source_key=:source_key "
                        "WHERE outbound.tenant_id=:tenant AND outbound.id=:outbound"
                    ),
                    {
                        "tenant": tenant_id,
                        "outbound": outbound_id,
                        "source_key": f"whatsapp:outbound:{outbound_id}:1",
                    },
                )
            )
            .mappings()
            .one()
        )
        usage_count = await session.scalar(
            text(
                "SELECT count(*) FROM public.usage_records "
                "WHERE tenant_id=:tenant AND kind='whatsapp'"
            ),
            {"tenant": tenant_id},
        )

    assert result.status == replay.status == row["status"] == "UNCERTAIN"
    assert row["provider_error_code"] == "send_outcome_unknown"
    assert row["attempt_count"] == 1
    assert len(interrupted_provider.text_requests) == 1
    assert replay_provider.text_requests == []
    assert usage_count == 1
    assert row["event"]["measurements"]["requests"] is None
    assert row["event"]["measurements"]["messages"] is None
    assert row["quote"]["amount"] is None
