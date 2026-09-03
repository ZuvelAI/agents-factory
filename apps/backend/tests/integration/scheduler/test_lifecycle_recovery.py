from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text

from apps.backend.tests.handoff_support import HandoffHarness
from apps.backend.tests.integration.runtime.test_agent_turn import _seed_inbound
from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401
from apps.backend.tests.integration.capabilities.test_appointments import world  # noqa: F401
from apps.backend.tests.approval_support import ApprovalHarness
from apps.backend.tests.appointments_support import NOW
from agents_factory.common.ids import new_uuid7
from agents_factory.common.queue import JobEnvelope
from agents_factory.modules.cases.models import CaseSubmission
from agents_factory.modules.cases.service import CaseService
from agents_factory.modules.capabilities.appointments.communications import (
    prepare_appointment_notification,
)
from scheduler.lifecycle_jobs import LifecycleJobs
from scheduler.lifecycle_scan import LifecycleScanner


async def due_jobs(sessions, tenant, now, topic):
    async with sessions.begin() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id,payload FROM public.outbox_jobs WHERE tenant_id=:tenant AND topic=:topic AND available_at<=:now"
                    ),
                    {"tenant": tenant, "topic": topic, "now": now},
                )
            )
            .mappings()
            .all()
        )
    return [
        JobEnvelope(row["id"], tenant, topic, UUID(row["payload"]["aggregate_id"]))
        for row in rows
    ]


async def test_recovery_clock_jumps_case_targets_handoff_and_no_pending_spam(
    session_factory,
):
    context, conversation, _ = await _seed_inbound(session_factory)
    context = replace(context, actor_id=new_uuid7(), actor_type="platform_admin")
    h = await HandoffHarness.create(session_factory, context, conversation)
    record = await h.request()
    await h.human_event(record)
    clock = [h.clock]
    cases = CaseService(session_factory, now=lambda: clock[0])
    pending = cases._new(
        CaseSubmission(
            tenant_id=context.tenant_id,
            customer_ref="customer",
            capability="orders",
            issue_type="cancellation",
            binding_id=new_uuid7(),
            resource_id="42",
            deduplication_key="0" * 64,
            content_digest="1" * 64,
            intake={},
            initial_status="OPEN",
        )
    ).model_copy(update={"status": "PENDING_APPROVAL"})
    resolved = pending.model_copy(
        update={
            "id": new_uuid7(),
            "deduplication_key": "2" * 64,
            "status": "RESOLVED",
            "resolved_at": clock[0],
            "close_at": clock[0] + timedelta(hours=72),
        }
    )
    async with cases.transaction(context) as repo:
        await repo.save(pending, new=True)
        await repo.save(resolved, new=True)
    scanner = LifecycleScanner(session_factory, now=lambda: clock[0])
    jobs = LifecycleJobs(session_factory, now=lambda: clock[0])
    assert await scanner.scan_tenant(context.tenant_id) == 0
    clock[0] += timedelta(hours=20)
    assert await scanner.scan_tenant(context.tenant_id) == 2
    assert await scanner.scan_tenant(context.tenant_id) == 0
    for job in await due_jobs(
        session_factory, context.tenant_id, clock[0], "cases.timer"
    ):
        await cases.process_timer(
            context=replace(context, actor_type="system"), case_id=job.aggregate_id
        )
    for job in await due_jobs(
        session_factory, context.tenant_id, clock[0], "handoffs.inactivity"
    ):
        await jobs.process(job)
        await jobs.process(job)
    assert (
        await h.service.status(context=h.context, handoff_id=record.id)
    ).status == "CLOSED"
    clock[0] += timedelta(hours=4)
    assert await scanner.scan_tenant(context.tenant_id) == 1
    await cases.process_timer(
        context=replace(context, actor_type="system"), case_id=pending.id
    )
    clock[0] += timedelta(hours=48)
    assert await scanner.scan_tenant(context.tenant_id) == 1
    await cases.process_timer(
        context=replace(context, actor_type="system"), case_id=resolved.id
    )
    assert await scanner.scan_tenant(context.tenant_id) == 0
    assert (
        await cases.get(context=context, customer_ref="customer", case_id=resolved.id)
    ).status == "CLOSED"
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='appointments.notify' OR topic='approvals.notify' OR topic='whatsapp.outbound.send'"
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE event_type='cases.response_target_alert'"
                )
            )
            == 2
        )


async def test_keyless_approval_and_action_expiry_are_idempotent(order_world):  # noqa: F811
    world = order_world  # noqa: F811
    h = await ApprovalHarness.create(world)
    action, request = await h.request()
    unconfirmed = await world.request(
        next(iter(world.bindings)),
        "orders.request_order_cancellation",
        {"order_id": "42", "reason": "Another request"},
    )
    now = request.expires_at + timedelta(seconds=1)
    scanner = LifecycleScanner(world.sessions, now=lambda: now)
    jobs = LifecycleJobs(world.sessions, now=lambda: now)  # No proof key/mailer/API.
    await scanner.scan_tenant(world.context.tenant_id)
    for topic in ("approvals.expire", "actions.expire"):
        for job in await due_jobs(world.sessions, world.context.tenant_id, now, topic):
            await jobs.process(job)
            await jobs.process(job)
    assert await scanner.scan_tenant(world.context.tenant_id) == 0
    async with world.sessions.begin() as session:
        states = (
            await session.scalars(
                text("SELECT state FROM public.actions WHERE id=ANY(:ids)"),
                {"ids": [action.id, unconfirmed.id]},
            )
        ).all()
        assert states == ["EXPIRED", "EXPIRED"]
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='approvals.result'"
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.approval_links WHERE request_id=:id AND invalidated_at IS NULL"
                ),
                {"id": request.id},
            )
            == 0
        )
    assert h.messages == []


async def test_missing_reminder_is_recovered_once_with_attendance_and_approved_template(
    world,  # noqa: F811
):  # noqa: F811
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
    booked = await world.execute(action)
    appointment_id = UUID(booked.result["data"]["id"])
    async with world.sessions.begin() as session:
        await session.execute(
            text(
                "DELETE FROM public.outbox_jobs WHERE tenant_id=:tenant AND topic='appointments.notify' AND payload->>'kind'='reminder'"
            ),
            {"tenant": world.context.tenant_id},
        )
    now = NOW + timedelta(hours=1, minutes=16)
    scanner = LifecycleScanner(world.sessions, now=lambda: now)
    assert await scanner.scan_tenant(world.context.tenant_id) == 1
    assert await scanner.scan_tenant(world.context.tenant_id) == 0
    notices = await due_jobs(
        world.sessions, world.context.tenant_id, now, "appointments.notify"
    )
    async with world.sessions.begin() as session:
        reminder_id = await session.scalar(
            text(
                "SELECT id FROM public.outbox_jobs WHERE topic='appointments.notify' AND payload->>'kind'='reminder'"
            )
        )
    envelope = next(job for job in notices if job.job_id == reminder_id)
    assert envelope.aggregate_id == appointment_id
    first = await prepare_appointment_notification(
        sessions=world.sessions, envelope=envelope, now=now
    )
    assert first == await prepare_appointment_notification(
        sessions=world.sessions, envelope=envelope, now=now
    )
    async with world.sessions.begin() as session:
        payload = await session.scalar(
            text("SELECT payload FROM public.outbound_messages WHERE id=:id"),
            {"id": first},
        )
        assert "Confirma tu asistencia" in str(payload)
        assert (
            await session.scalar(text("SELECT count(*) FROM public.outbound_messages"))
            == 1
        )
