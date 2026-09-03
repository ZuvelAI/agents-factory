from datetime import timedelta
from sqlalchemy import text

from apps.backend.tests.integration.capabilities.test_appointments import world  # noqa: F401
from apps.backend.tests.integration.scheduler.test_lifecycle_recovery import due_jobs
from apps.backend.tests.appointments_support import NOW, configuration
from agents_factory.modules.capabilities.appointments.communications import (
    prepare_appointment_notification,
)
from scheduler.lifecycle_scan import LifecycleScanner


async def test_changed_timing_defers_or_advances_without_double_delivery(world):  # noqa: F811
    action = await world.request(
        "create_appointment",
        {
            "service_id": "consultation",
            "professional_id": "professional",
            "location_id": "office",
            "start": "2026-09-01T14:15:00Z",
        },
        level=1,
    )
    await world.confirm(action)
    await world.execute(action)
    original = configuration()
    await world.appointments.configure(
        original.model_copy(
            update={
                "communications": original.communications.model_copy(
                    update={"reminder_minutes_before": 30}
                )
            }
        )
    )
    now = NOW + timedelta(hours=1, minutes=16)
    async with world.sessions.begin() as session:
        old_id = await session.scalar(
            text(
                "SELECT id FROM public.outbox_jobs WHERE topic='appointments.notify' AND payload->>'kind'='reminder'"
            )
        )
    old = next(
        job
        for job in await due_jobs(
            world.sessions, world.context.tenant_id, now, "appointments.notify"
        )
        if job.job_id == old_id
    )
    assert (
        await prepare_appointment_notification(
            sessions=world.sessions, envelope=old, now=now
        )
        is None
    )
    await world.appointments.configure(
        original.model_copy(
            update={
                "communications": original.communications.model_copy(
                    update={"reminder_minutes_before": 90}
                )
            }
        )
    )
    scanner = LifecycleScanner(world.sessions, now=lambda: now)
    assert await scanner.scan_tenant(world.context.tenant_id) == 1
    async with world.sessions.begin() as session:
        advanced_id = await session.scalar(
            text(
                "SELECT id FROM public.outbox_jobs WHERE topic='appointments.notify' AND payload->>'kind'='reminder' AND id<>:old AND available_at<=:now"
            ),
            {"old": old_id, "now": now},
        )
    advanced = next(
        job
        for job in await due_jobs(
            world.sessions, world.context.tenant_id, now, "appointments.notify"
        )
        if job.job_id == advanced_id
    )
    sent = await prepare_appointment_notification(
        sessions=world.sessions, envelope=advanced, now=now
    )
    assert sent is not None
    assert sent == await prepare_appointment_notification(
        sessions=world.sessions, envelope=old, now=now
    )
    assert await scanner.scan_tenant(world.context.tenant_id) == 0
    async with world.sessions.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.outbound_messages"))
            == 1
        )
