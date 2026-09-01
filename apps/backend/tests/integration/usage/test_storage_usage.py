from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.modules.usage.models import (
    CommercialPolicy,
    PriceCard,
    QuotaWindow,
    UnitPrice,
    UsageConfiguration,
)
from agents_factory.modules.usage.recorder import UsageRecorder
from agents_factory.modules.usage.storage import StorageUsageAllocator


async def test_hourly_private_storage_allocation_is_exact_and_idempotent(
    session_factory,
) -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    tenant_id, source_id = uuid4(), uuid4()
    ingestion_ids = (uuid4(), uuid4())
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name) "
                "VALUES (:id,:slug,'Storage usage')"
            ),
            {"id": tenant_id, "slug": f"storage-usage-{tenant_id}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.knowledge_sources"
                "(id,tenant_id,name,source_type,authority,created_at) "
                "VALUES (:id,:tenant,'Storage source','MANUAL','AUTHORITATIVE',:at)"
            ),
            {"id": source_id, "tenant": tenant_id, "at": start - timedelta(days=1)},
        )
        for index, (ingestion_id, size, stored_at) in enumerate(
            (
                (ingestion_ids[0], 100, start),
                (ingestion_ids[1], 40, start + timedelta(minutes=30)),
            ),
            start=1,
        ):
            await session.execute(
                text(
                    "INSERT INTO public.knowledge_ingestions"
                    "(id,tenant_id,source_id,state,created_at,updated_at) "
                    "VALUES (:id,:tenant,:source,'PENDING',:created,:created)"
                ),
                {
                    "id": ingestion_id,
                    "tenant": tenant_id,
                    "source": source_id,
                    "created": start - timedelta(minutes=1),
                },
            )
            await session.execute(
                text(
                    "UPDATE public.knowledge_ingestions SET state='PROCESSING' "
                    "WHERE id=:id"
                ),
                {"id": ingestion_id},
            )
            await session.execute(
                text(
                    "UPDATE public.knowledge_ingestions SET state='SUCCEEDED',"
                    "content_digest=:digest,storage_path=:path,byte_size=:size,"
                    "stored_at=:stored,completed_at=:stored,updated_at=:stored "
                    "WHERE id=:id"
                ),
                {
                    "id": ingestion_id,
                    "digest": str(index) * 64,
                    "path": f"{tenant_id}/{source_id}/originals/{index}",
                    "size": size,
                    "stored": stored_at,
                },
            )

    context = TenantContext(tenant_id, uuid4(), "platform_admin", uuid4())
    recorder = UsageRecorder(session_factory)
    await recorder.configure(
        context=context,
        configuration=UsageConfiguration(
            prices=(
                PriceCard(
                    id=uuid4(),
                    provider="agents_factory",
                    product="private_originals",
                    kind="storage",
                    currency="USD",
                    effective_from=start - timedelta(days=1),
                    rates={"storage_byte_hours": UnitPrice(amount=Decimal("0.001"))},
                ),
            ),
            commercial=CommercialPolicy(storage_bytes=120, alert_percentages=(100,)),
            quota_window=QuotaWindow(start=start, end=end + timedelta(hours=1)),
        ),
        expected_revision=0,
    )
    allocator = StorageUsageAllocator(session_factory, recorder=recorder)

    assert await allocator.record_next_completed_hour(
        context=context, through=end + timedelta(minutes=10)
    )
    assert not await allocator.record_next_completed_hour(
        context=context, through=end + timedelta(minutes=10)
    )

    async with session_factory.begin() as session:
        usage = (
            (
                await session.execute(
                    text(
                        "SELECT event,quote FROM public.usage_records "
                        "WHERE tenant_id=:tenant AND kind='storage'"
                    ),
                    {"tenant": tenant_id},
                )
            )
            .mappings()
            .one()
        )
        alert = (
            (
                await session.execute(
                    text(
                        "SELECT metric,threshold,state FROM public.usage_alerts "
                        "WHERE tenant_id=:tenant AND metric='storage_bytes'"
                    ),
                    {"tenant": tenant_id},
                )
            )
            .mappings()
            .one()
        )

    assert usage["event"]["measurements"]["storage_bytes"] == 140
    assert Decimal(usage["event"]["measurements"]["storage_byte_hours"]) == Decimal(120)
    assert Decimal(usage["quote"]["amount"]) == Decimal("0.12")
    assert dict(alert) == {
        "metric": "storage_bytes",
        "threshold": 100,
        "state": "grace_overage",
    }
