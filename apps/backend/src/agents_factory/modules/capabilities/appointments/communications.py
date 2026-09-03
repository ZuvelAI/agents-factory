from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.audit import AuditService
from agents_factory.common.outbox import OutboxService
from agents_factory.common.queue import JobEnvelope
from agents_factory.modules.capabilities.appointments.repository import (
    AppointmentRepository,
    AppointmentUnavailable,
)
from agents_factory.modules.whatsapp.template_service import TemplateService


async def prepare_appointment_notification(
    *,
    sessions: async_sessionmaker[AsyncSession],
    envelope: JobEnvelope,
    now: datetime | None = None,
) -> UUID | None:
    if envelope.kind != "appointments.notify":
        raise AppointmentUnavailable("invalid_notification_job")
    current = now or datetime.now(UTC)
    context = TenantContext(
        envelope.tenant_id, envelope.job_id, "system", envelope.job_id
    )
    async with sessions.begin() as guard:
        key = int.from_bytes(
            hashlib.sha256(f"appointments:{context.tenant_id}".encode()).digest()[:8],
            "big",
            signed=True,
        )
        await guard.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        async with sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            repository = AppointmentRepository(session, context)
            await repository.scope()
            job = (
                (
                    await session.execute(
                        text(
                            "SELECT payload, available_at, idempotency_key FROM public.outbox_jobs WHERE id = :id AND tenant_id = :tenant AND topic = 'appointments.notify'"
                        ),
                        {"id": envelope.job_id, "tenant": context.tenant_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if job is None or job["available_at"] > current:
                raise AppointmentUnavailable("notification_not_due")
            payload = job["payload"]
            if payload.get("appointment_id") != str(envelope.aggregate_id):
                raise AppointmentUnavailable("notification_binding_mismatch")
            appointment = await repository.get(envelope.aggregate_id)
            if payload.get("revision") != appointment.revision:
                return None
            kind = payload.get("kind")
            if kind not in {"confirmation", "reminder", "cancellation_request"}:
                raise AppointmentUnavailable("invalid_notification_kind")
            if kind == "reminder" and (
                appointment.status != "BOOKED" or appointment.start <= current
            ):
                return None
            config = await repository.config()
            if kind == "reminder":
                due = appointment.start.astimezone(UTC) - timedelta(
                    minutes=config.communications.reminder_minutes_before
                )
                if current < due:
                    # Recheck tenant timing after dispatch. The replacement is
                    # a locator; customer delivery retains one canonical key.
                    await OutboxService(session).enqueue(
                        context=context,
                        topic="appointments.notify",
                        idempotency_key=f"appointments.notify:{appointment.id}:{appointment.revision}:reminder:timing:{due.isoformat()}",
                        payload={**payload, "scheduled_for": due.isoformat()},
                        available_at=due,
                    )
                    await AuditService(session).record(
                        context=context,
                        event_type="schedule.reminder_deferred",
                        entity_type="appointment",
                        entity_id=appointment.id,
                        payload={
                            "due_at": due.isoformat(),
                            "revision": appointment.revision,
                        },
                    )
                    return None
            recipient = await session.scalar(
                text(
                    "SELECT customer_wa_id FROM public.conversations WHERE tenant_id = :tenant AND id = :conversation AND whatsapp_account_id = :account AND control_state = 'AI_ACTIVE'"
                ),
                {
                    "tenant": context.tenant_id,
                    "conversation": appointment.conversation_id,
                    "account": config.communications.whatsapp_account_id,
                },
            )
            if not isinstance(recipient, str):
                return None
        communication = config.communications
        template_name = {
            "confirmation": communication.confirmation_template,
            "reminder": communication.reminder_template,
            "cancellation_request": communication.cancellation_request_template,
        }[kind]
        # Attendance confirmation and rescheduling instructions belong to the one
        # approved reminder, not extra reminders or model-defined message templates.
        spanish = communication.language.startswith("es")
        variables = {
            "appointment_id": str(appointment.id),
            "service": config.service(appointment.service_id).name,
            "professional": config.main_professional.name,
            "location": config.location.name,
            "start": appointment.start.astimezone(
                ZoneInfo(config.timezone)
            ).isoformat(),
        }
        if kind == "reminder":
            variables.update(
                {
                    "attendance_confirmation": "Confirma tu asistencia respondiendo a este mensaje."
                    if spanish
                    else "Reply to confirm your attendance.",
                    "reschedule_option": "Si necesitas reprogramar, solicita otro horario."
                    if spanish
                    else "To reschedule, request another time.",
                }
            )
        return await TemplateService(
            session_factory=sessions, context=context
        ).prepare_proactive(
            whatsapp_account_id=communication.whatsapp_account_id,
            recipient_wa_id=recipient,
            template_name=template_name,
            language=communication.language,
            variables=variables,
            idempotency_key=f"appointments.notify:{appointment.id}:{appointment.revision}:{kind}",
            conversation_id=appointment.conversation_id,
        )
