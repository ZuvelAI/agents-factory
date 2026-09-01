from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from apps.backend.tests.integration.test_outbound_idempotency import (
    RecordingProvider,
    _seed_text_reply,
)
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.usage.models import PriceCard, UnitPrice, UsageConfiguration
from agents_factory.modules.usage.recorder import UsageRecorder
from agents_factory.modules.whatsapp.contracts import (
    ProviderMessageResult,
    WhatsAppDeliveryStatusEvent,
)
from agents_factory.modules.whatsapp.outbound_service import (
    OutboundMessageService,
    OutboundStatusReconciler,
)


async def test_meta_cost_callback_is_priced_once_without_double_counting_messages(
    session_factory,
) -> None:
    tenant_id, account_id, _, assistant_id = await _seed_text_reply(session_factory)
    actor_id = new_uuid7()
    context = TenantContext(tenant_id, actor_id, "system", actor_id)
    recorder = UsageRecorder(session_factory)
    now = datetime.now(UTC)
    await recorder.configure(
        context=TenantContext(tenant_id, actor_id, "platform_admin", actor_id),
        configuration=UsageConfiguration(
            prices=(
                PriceCard(
                    id=new_uuid7(),
                    provider="meta",
                    product="whatsapp_cloud_api.text.service",
                    kind="whatsapp",
                    currency="USD",
                    effective_from=now - timedelta(days=1),
                    rates={"billable_messages": UnitPrice(amount=Decimal("0.02"))},
                ),
            )
        ),
        expected_revision=0,
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=context,
        provider=RecordingProvider(
            [
                ProviderMessageResult(
                    outcome="accepted", provider_message_id="wamid.cost.1"
                )
            ]
        ),
        usage_recorder=recorder,
    )
    outbound_id = await service.prepare_text(message_id=assistant_id)
    await service.send(outbound_id)
    callback = WhatsAppDeliveryStatusEvent(
        waba_id="waba-test",
        phone_number_id="phone-test",
        whatsapp_message_id="wamid.cost.1",
        recipient_wa_id="573000000001",
        status="delivered",
        occurred_at=now,
        raw_payload={},
        cost_attribution={
            "billable": True,
            "category": "service",
            "pricing_model": "CBP",
        },
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        reconciler = OutboundStatusReconciler(session, usage_recorder=recorder)
        assert await reconciler.reconcile(
            context=context, whatsapp_account_id=account_id, event=callback
        )
        assert await reconciler.reconcile(
            context=context, whatsapp_account_id=account_id, event=callback
        )

    async with session_factory.begin() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT product,event,quote FROM public.usage_records "
                        "WHERE tenant_id=:tenant AND kind='whatsapp' ORDER BY product"
                    ),
                    {"tenant": tenant_id},
                )
            )
            .mappings()
            .all()
        )

    assert len(rows) == 2
    assert sum(row["event"]["measurements"]["messages"] for row in rows) == 1
    cost = next(row for row in rows if row["product"].endswith(".service"))
    assert cost["event"]["measurements"]["billable_messages"] == 1
    assert cost["event"]["whatsapp"] == {
        "billable": True,
        "category": "service",
        "pricing_model": "CBP",
        "recipient_market": None,
    }
    assert Decimal(cost["quote"]["amount"]) == Decimal("0.02")
