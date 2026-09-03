from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.actions.models import ActionRecord
from agents_factory.modules.capabilities.appointments.models import (
    Appointment,
    AppointmentsConfig,
    BusyInterval,
)
from agents_factory.modules.integrations.contracts import ConnectorResult


class AppointmentUnavailable(ValueError):
    """Safe business reason; never includes provider data or another customer's IDs."""


class AppointmentRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context

    async def scope(self) -> None:
        await set_tenant_context(self.session, self.context.tenant_id)

    async def config(self) -> AppointmentsConfig:
        await self.scope()
        value = await self.session.scalar(
            text(
                "SELECT configuration FROM public.appointment_configurations WHERE tenant_id = :tenant"
            ),
            {"tenant": self.context.tenant_id},
        )
        if value is None:
            raise AppointmentUnavailable("appointments_not_configured")
        return AppointmentsConfig.model_validate(value)

    async def configure(self, configuration: AppointmentsConfig) -> None:
        if self.context.actor_type != "platform_admin" or self.context.actor_id is None:
            raise AppointmentUnavailable("platform_admin_required")
        await self.scope()
        valid = await self.session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.integration_connections WHERE tenant_id = :tenant AND id = :connection AND connector_name = 'google_calendar')"
            ),
            {
                "tenant": self.context.tenant_id,
                "connection": configuration.connection_id,
            },
        )
        if not valid:
            raise AppointmentUnavailable("calendar_connection_required")
        previous = await self.session.scalar(
            text(
                "SELECT configuration FROM public.appointment_configurations WHERE tenant_id = :tenant FOR UPDATE"
            ),
            {"tenant": self.context.tenant_id},
        )
        if previous is not None:
            old = AppointmentsConfig.model_validate(previous)
            # Never silently move existing appointments to a different calendar/resource.
            immutable = (
                "binding_id",
                "connection_id",
                "calendar_id",
                "main_professional",
                "location",
                "timezone",
            )
            if any(
                getattr(old, field) != getattr(configuration, field)
                for field in immutable
            ):
                raise AppointmentUnavailable("resource_reconfiguration_unavailable")
        await self.session.execute(
            text(
                "INSERT INTO public.appointment_configurations (tenant_id, connection_id, configuration) VALUES (:tenant, :connection, :configuration) ON CONFLICT (tenant_id) DO UPDATE SET configuration = excluded.configuration, updated_at = now()"
            ).bindparams(bindparam("configuration", type_=JSONB)),
            {
                "tenant": self.context.tenant_id,
                "connection": configuration.connection_id,
                "configuration": configuration.model_dump(mode="json"),
            },
        )

    async def get(
        self, appointment_id: UUID, *, customer_ref: str | None = None
    ) -> Appointment:
        await self.scope()
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.appointments WHERE tenant_id = :tenant AND id = :id"
                    ),
                    {"tenant": self.context.tenant_id, "id": appointment_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or (
            customer_ref is not None and row["customer_ref"] != customer_ref
        ):
            raise AppointmentUnavailable("appointment_not_found")
        data = dict(row)
        data["start"], data["end"] = data.pop("start_at"), data.pop("end_at")
        return Appointment.model_validate(data)

    async def busy(
        self, start: datetime, end: datetime, *, exclude: UUID | None = None
    ) -> tuple[BusyInterval, ...]:
        await self.scope()
        rows = (
            await self.session.execute(
                text(
                    "SELECT busy_start, busy_end FROM public.appointments WHERE tenant_id = :tenant AND busy_start < :end AND busy_end > :start AND (cast(:exclude as uuid) IS NULL OR id <> :exclude)"
                ),
                {
                    "tenant": self.context.tenant_id,
                    "start": start,
                    "end": end,
                    "exclude": exclude,
                },
            )
        ).mappings()
        return tuple(
            BusyInterval(start=row["busy_start"], end=row["busy_end"]) for row in rows
        )

    async def save(self, appointment: Appointment) -> None:
        await self.scope()
        if appointment.tenant_id != self.context.tenant_id:
            raise AppointmentUnavailable("tenant_mismatch")
        values = appointment.model_dump()
        values["start_at"], values["end_at"] = values.pop("start"), values.pop("end")
        columns = tuple(values)
        # Identifiers derive only from code-owned Pydantic fields, not user input.
        update = ", ".join(
            f"{column} = excluded.{column}"
            for column in (
                "start_at",
                "end_at",
                "busy_start",
                "busy_end",
                "etag",
                "status",
                "revision",
                "last_action_id",
            )
        )
        await self.session.execute(
            text(
                f"INSERT INTO public.appointments ({', '.join(columns)}) VALUES ({', '.join(':' + key for key in columns)}) ON CONFLICT (id) DO UPDATE SET {update} WHERE appointments.tenant_id = excluded.tenant_id"
            ),
            values,
        )

    async def receipt(self, action: ActionRecord) -> ConnectorResult | None:
        await self.scope()
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT operation, parameter_digest, status, result FROM public.appointment_operations WHERE tenant_id = :tenant AND id = :id"
                    ),
                    {"tenant": self.context.tenant_id, "id": action.id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if (
            row["parameter_digest"] != action.parameter_digest
            or row["operation"] != action.action_type
        ):
            raise AppointmentUnavailable("action_idempotency_conflict")
        if row["status"] == "CLAIMED":
            return ConnectorResult(
                operation=action.action_type,
                status="UNCERTAIN",
                error_code="interrupted_appointment_execution",
            )
        return ConnectorResult.model_validate(row["result"])

    async def claim(self, action: ActionRecord) -> None:
        await self.scope()
        await self.session.execute(
            text(
                "INSERT INTO public.appointment_operations (id, tenant_id, operation, parameter_digest, status) VALUES (:id, :tenant, :operation, :digest, 'CLAIMED')"
            ),
            {
                "id": action.id,
                "tenant": self.context.tenant_id,
                "operation": action.action_type,
                "digest": action.parameter_digest,
            },
        )

    async def finish(self, action: ActionRecord, result: ConnectorResult) -> None:
        await self.scope()
        await self.session.execute(
            text(
                "UPDATE public.appointment_operations SET status = :status, result = :result, updated_at = now() WHERE tenant_id = :tenant AND id = :id"
            ).bindparams(bindparam("result", type_=JSONB)),
            {
                "tenant": self.context.tenant_id,
                "id": action.id,
                "status": result.status,
                "result": result.model_dump(mode="json"),
            },
        )
