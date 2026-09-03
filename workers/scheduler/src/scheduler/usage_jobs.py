from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import Database
from agents_factory.modules.usage.storage import StorageUsageAllocator


def configure_usage_jobs(context: dict[Any, Any], *, database: Database) -> None:
    context["storage_usage_allocator"] = StorageUsageAllocator(database.session_factory)


async def record_storage_usage(context: dict[Any, Any]) -> dict[str, int]:
    allocator = cast(StorageUsageAllocator, context["storage_usage_allocator"])
    tenants = await allocator.tenants(after=context.get("storage_usage_cursor"))
    if not tenants:
        context["storage_usage_cursor"] = None
        return {"tenants": 0, "recorded": 0, "failed_tenants": 0}
    recorded, failures = 0, 0
    through = datetime.now(UTC)
    for tenant_id in tenants:
        actor_id = new_uuid7()
        try:
            recorded += int(
                await allocator.record_next_completed_hour(
                    context=TenantContext(
                        tenant_id=tenant_id,
                        actor_id=actor_id,
                        actor_type="system",
                        correlation_id=actor_id,
                    ),
                    through=through,
                )
            )
        except Exception:
            failures += 1
    context["storage_usage_cursor"] = tenants[-1]
    return {
        "tenants": len(tenants),
        "recorded": recorded,
        "failed_tenants": failures,
    }
