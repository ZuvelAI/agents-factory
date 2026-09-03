from datetime import timedelta

from sqlalchemy import text

from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401
from scheduler.lifecycle_scan import LifecycleScanner


async def test_retry_backoff_does_not_starve_the_next_bounded_scan(order_world):  # noqa: F811
    actions = [
        await order_world.request(
            next(iter(order_world.bindings)),
            "orders.request_order_cancellation",
            {"order_id": "42", "reason": reason},
        )
        for reason in ("First confirmation", "Second confirmation")
    ]
    now = max(a.confirmation_expires_at for a in actions) + timedelta(seconds=1)
    scanner = LifecycleScanner(order_world.sessions, now=lambda: now)
    assert await scanner.scan_tenant(order_world.context.tenant_id, limit=1) == 1
    async with order_world.sessions.begin() as session:
        await session.execute(
            text(
                "UPDATE public.outbox_jobs SET available_at=:retry WHERE tenant_id=:tenant AND topic='actions.expire'"
            ),
            {
                "tenant": order_world.context.tenant_id,
                "retry": now + timedelta(minutes=1),
            },
        )
    # Dispatch retry moves available_at, not the original scheduling identity.
    assert await scanner.scan_tenant(order_world.context.tenant_id, limit=1) == 1
    assert await scanner.scan_tenant(order_world.context.tenant_id, limit=1) == 0
