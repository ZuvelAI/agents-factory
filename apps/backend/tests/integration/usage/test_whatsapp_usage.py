from decimal import Decimal

from sqlalchemy import text

from apps.backend.tests.integration.test_outbound_idempotency import (
    RecordingProvider,
    _seed_text_reply,
)
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.usage.recorder import UsageRecorder
from agents_factory.modules.whatsapp.contracts import ProviderMessageResult
from agents_factory.modules.whatsapp.outbound_service import OutboundMessageService


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
