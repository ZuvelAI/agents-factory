from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.actions.models import (
    ActionRecord,
    NormalizedParameters,
    PreconditionDecision,
)
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.capabilities.appointments.availability import (
    available_slots,
    candidate_slot,
    is_free,
)
from agents_factory.modules.capabilities.appointments.manifest import (
    DEFINITIONS,
    action_gate,
)
from agents_factory.modules.capabilities.appointments.models import (
    Appointment,
    AppointmentsConfig,
    BusyInterval,
    INPUTS,
)
from agents_factory.modules.capabilities.appointments.repository import (
    AppointmentRepository,
    AppointmentUnavailable,
)
from agents_factory.modules.identity.models import (
    AuthorizationDecision,
    IdentityAssessment,
    IdentityLevel,
)
from agents_factory.modules.integrations.contracts import (
    Connector,
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.policies.models import TenantActionPolicy


class CalendarFactory(Protocol):
    def __call__(self, config: AppointmentsConfig) -> Connector: ...


class CalendarOperationFailed(Exception):
    def __init__(self, result: ConnectorResult) -> None:
        self.result = result
        super().__init__(result.error_code or "calendar_failed")


def configuration_digest(config: AppointmentsConfig) -> str:
    value = config.model_dump(mode="json")
    value["closed_dates"] = sorted(day.isoformat() for day in config.closed_dates)
    return NormalizedParameters.from_value(value).digest


class AppointmentsService:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        context: TenantContext,
        calendar: CalendarFactory,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions, self.context, self.calendar = sessions, context, calendar
        self.now = now or (lambda: datetime.now(UTC))

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AppointmentRepository]:
        if (
            self.context.actor_type not in {"system", "platform_admin"}
            or self.context.actor_id is None
        ):
            raise AppointmentUnavailable("backend_actor_required")
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            yield AppointmentRepository(session, self.context)

    @asynccontextmanager
    async def resource_lock(self) -> AsyncIterator[None]:
        # Transaction-level mutex, not a customer slot hold. The guard transaction
        # stays open while attempt/results commit independently. Safe with pooling.
        async with self.sessions.begin() as session:
            key = int.from_bytes(
                hashlib.sha256(
                    f"appointments:{self.context.tenant_id}".encode()
                ).digest()[:8],
                "big",
                signed=True,
            )
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": key}
            )
            yield

    async def configure(self, config: AppointmentsConfig) -> None:
        async with self.resource_lock(), self.transaction() as repository:
            await repository.configure(config)
            await AuditService(repository.session).record(
                context=self.context,
                event_type="appointments.configured",
                entity_type="tenant",
                entity_id=self.context.tenant_id,
                payload={"configuration_digest": configuration_digest(config)},
            )

    async def request_action(
        self,
        *,
        actions: ActionService,
        action_id: UUID,
        conversation_id: UUID,
        customer_ref: str,
        operation: str,
        arguments: dict[str, object],
        assessment: IdentityAssessment,
        tenant_policy: TenantActionPolicy | None = None,
    ) -> ActionRecord:
        if (
            operation not in INPUTS
            or assessment.tenant_id != self.context.tenant_id
            or assessment.customer_ref != customer_ref
        ):
            raise AppointmentUnavailable("appointment_not_authorized")
        parameters = INPUTS[operation].model_validate(arguments).model_dump(mode="json")
        if "start" in parameters:
            parameters["start"] = (
                datetime.fromisoformat(str(parameters["start"]))
                .astimezone(UTC)
                .isoformat()
            )
        async with self.transaction() as repository:
            config = await repository.config()
            if "appointment_id" in parameters:
                appointment = await repository.get(
                    UUID(str(parameters["appointment_id"])), customer_ref=customer_ref
                )
                resource_id = str(appointment.id)
            else:
                resource_id = config.service(str(parameters["service_id"])).id
            if operation == "appointments.create_appointment" and (
                parameters["professional_id"] != config.main_professional.id
                or parameters["location_id"] != config.location.id
            ):
                raise AppointmentUnavailable("resource_configuration_unavailable")
        parameters["configuration_digest"] = configuration_digest(config)
        definition = DEFINITIONS[operation]
        return await actions.request(
            action_id=action_id,
            conversation_id=conversation_id,
            customer_ref=customer_ref,
            capability="appointments",
            action_type=operation,
            risk=definition.risk,
            minimum_identity_level=IdentityLevel(definition.required_identity_level),
            tenant_policy=tenant_policy,
            assessment=assessment,
            authorization=AuthorizationDecision(
                tenant_id=self.context.tenant_id,
                customer_ref=customer_ref,
                resource_type="appointment",
                resource_id=resource_id,
                action=operation,
                allowed=True,
                reason_code="tenant_resource_owner",
            ),
            resource_type="appointment",
            resource_id=resource_id,
            parameters=parameters,
            approval_route_ref=config.approval_route_ref
            if definition.requires_approval
            or (tenant_policy is not None and tenant_policy.approval_required)
            else None,
            connector_binding_id=config.binding_id,
            connector_name="google_calendar",
            requested_at=self.now(),
        )

    async def _call(
        self,
        config: AppointmentsConfig,
        operation: str,
        arguments: dict[str, object],
        *,
        action_id: UUID | None = None,
    ) -> dict[str, object]:
        result = await self.calendar(config).execute(
            ConnectorRequest(
                tenant_id=self.context.tenant_id,
                binding_id=config.binding_id,
                operation=operation,
                arguments=arguments,
                idempotency_key=str(action_id) if action_id is not None else None,
            )
        )
        if result.status != "SUCCEEDED":
            raise CalendarOperationFailed(result)
        return result.data

    async def _occupied(
        self,
        config: AppointmentsConfig,
        start: datetime,
        end: datetime,
        *,
        exclude: Appointment | None = None,
    ) -> tuple[BusyInterval, ...]:
        args: dict[str, object] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": config.timezone,
        }
        occupied: list[BusyInterval] = []
        if exclude is None:
            data = await self._call(config, "calendar.check_availability", args)
            periods = data.get("busy")
            if not isinstance(periods, list):
                raise AppointmentUnavailable("availability_unknown")
            occupied.extend(BusyInterval.model_validate(period) for period in periods)
        else:
            data = await self._call(config, "calendar.list_events", args)
            events = data.get("events")
            if not isinstance(events, list):
                raise AppointmentUnavailable("availability_unknown")
            for event in events:
                if not isinstance(event, dict):
                    raise AppointmentUnavailable("availability_unknown")
                if (
                    event.get("event_id") == exclude.external_event_id
                    or event.get("status") == "cancelled"
                    or event.get("transparency") == "transparent"
                ):
                    continue
                occupied.append(_event_interval(event, config.timezone))
        async with self.transaction() as repository:
            occupied.extend(
                await repository.busy(
                    start, end, exclude=exclude.id if exclude else None
                )
            )
        return tuple(occupied)

    async def _execute_authorized(self, action: ActionRecord) -> ConnectorResult:
        write = DEFINITIONS[action.action_type].risk != "LOW"
        async with self.resource_lock():
            async with self.transaction() as repository:
                config = await repository.config()
                if write:
                    prior = await repository.receipt(action)
                    if prior is not None:
                        return prior
                    await repository.claim(action)
            # The claim is durable BEFORE any external write. A crash can never
            # turn this action into a blind retry, even if the outer action rolls back.
            appointment: Appointment | None = None
            try:
                if action.parameters.get(
                    "configuration_digest"
                ) != configuration_digest(config):
                    raise AppointmentUnavailable("configuration_changed")
                arguments = {
                    key: value
                    for key, value in action.parameters.items()
                    if key != "configuration_digest"
                }
                INPUTS[action.action_type].model_validate(arguments)
                result, appointment = await self._perform(config, action, arguments)
            except CalendarOperationFailed as error:
                result = ConnectorResult(
                    operation=action.action_type,
                    status=error.result.status,
                    error_code=error.result.error_code or "calendar_failed",
                )
            except (AppointmentUnavailable, ValidationError, ValueError) as error:
                reason = (
                    str(error)
                    if isinstance(error, AppointmentUnavailable)
                    else "invalid_appointment_parameters"
                )
                result = ConnectorResult(
                    operation=action.action_type, status="REJECTED", error_code=reason
                )
            except Exception:
                result = ConnectorResult(
                    operation=action.action_type,
                    status="UNCERTAIN" if write else "FAILED",
                    error_code="appointment_execution_error",
                )
            if write:
                async with self.transaction() as repository:
                    if appointment is not None and result.status == "SUCCEEDED":
                        await repository.save(appointment)
                        await self._queue_communications(
                            repository, config, appointment, action
                        )
                    await repository.finish(action, result)
                    await AuditService(repository.session).record(
                        context=self.context,
                        event_type="appointments.operation",
                        entity_type="action",
                        entity_id=action.id,
                        payload={
                            "operation": action.action_type,
                            "status": result.status,
                            "error_code": result.error_code,
                        },
                    )
            return result

    async def _perform(
        self, config: AppointmentsConfig, action: ActionRecord, args: dict[str, object]
    ) -> tuple[ConnectorResult, Appointment | None]:
        operation = action.action_type
        appointment: Appointment | None = None
        if "appointment_id" in args:
            async with self.transaction() as repository:
                appointment = await repository.get(
                    UUID(str(args["appointment_id"])), customer_ref=action.customer_ref
                )
            live = await self._call(
                config,
                "calendar.get_event",
                {"event_id": appointment.external_event_id},
            )
            if operation == "appointments.get_appointment":
                interval = _event_interval(live, config.timezone)
                return ConnectorResult(
                    operation=operation,
                    status="SUCCEEDED",
                    data={
                        **appointment.public(),
                        "start": interval.start.isoformat(),
                        "end": interval.end.isoformat(),
                        "provider_status": live.get("status", "confirmed"),
                    },
                ), None
            if live.get("status") == "cancelled":
                raise AppointmentUnavailable("appointment_already_cancelled")
            if live.get("etag") != appointment.etag:
                raise AppointmentUnavailable("appointment_changed")
            if appointment.status != "BOOKED":
                raise AppointmentUnavailable("cancellation_already_requested")
        if operation == "appointments.check_availability":
            day = date.fromisoformat(str(args["day"]))
            start = datetime.combine(
                day, time.min, tzinfo=ZoneInfo(config.timezone)
            ).astimezone(UTC)
            end = datetime.combine(
                day + timedelta(days=1), time.min, tzinfo=ZoneInfo(config.timezone)
            ).astimezone(UTC)
            occupied = await self._occupied(config, start, end)
            slots = available_slots(
                config, str(args["service_id"]), day, now=self.now(), occupied=occupied
            )
            return ConnectorResult(
                operation=operation,
                status="SUCCEEDED",
                data={
                    "slots": [
                        {"start": slot.start.isoformat(), "end": slot.end.isoformat()}
                        for slot in slots
                    ],
                    "timezone": config.timezone,
                    "professional_id": config.main_professional.id,
                    "location_id": config.location.id,
                    "held": False,
                },
            ), None
        if operation == "appointments.request_cancellation":
            assert appointment is not None
            updated = appointment.model_copy(
                update={
                    "status": "CANCELLATION_REQUESTED",
                    "revision": appointment.revision + 1,
                    "last_action_id": action.id,
                }
            )
            return ConnectorResult(
                operation=operation,
                status="SUCCEEDED",
                data={**updated.public(), "cancellation_executed": False},
            ), updated
        if appointment is None:
            if (
                args.get("professional_id") != config.main_professional.id
                or args.get("location_id") != config.location.id
            ):
                raise AppointmentUnavailable("resource_configuration_unavailable")
            service_id = str(args["service_id"])
        else:
            service_id = appointment.service_id
        service = config.service(service_id)
        slot = candidate_slot(
            config, service, datetime.fromisoformat(str(args["start"])), now=self.now()
        )
        if slot is None:
            raise AppointmentUnavailable("booking_policy_denied")
        # Inside the resource mutex, immediately before provider mutation.
        occupied = await self._occupied(
            config, slot.busy_start, slot.busy_end, exclude=appointment
        )
        if not is_free(slot, occupied):
            raise AppointmentUnavailable("slot_unavailable")
        provider_args: dict[str, object] = {
            "start": slot.start.isoformat(),
            "end": slot.end.isoformat(),
            "timezone": config.timezone,
        }
        if appointment is None:
            provider_args["summary"] = service.name
            data = await self._call(
                config, "calendar.create_event", provider_args, action_id=action.id
            )
            appointment = Appointment(
                id=uuid5(action.id, "appointment"),
                tenant_id=action.tenant_id,
                customer_ref=action.customer_ref,
                conversation_id=action.conversation_id,
                service_id=service_id,
                professional_id=config.main_professional.id,
                location_id=config.location.id,
                start=slot.start,
                end=slot.end,
                busy_start=slot.busy_start,
                busy_end=slot.busy_end,
                external_event_id=_string(data, "event_id"),
                etag=_string(data, "etag"),
                last_action_id=action.id,
            )
        else:
            provider_args.update(
                {"event_id": appointment.external_event_id, "etag": appointment.etag}
            )
            data = await self._call(
                config, "calendar.reschedule_event", provider_args, action_id=action.id
            )
            appointment = appointment.model_copy(
                update={
                    "start": slot.start,
                    "end": slot.end,
                    "busy_start": slot.busy_start,
                    "busy_end": slot.busy_end,
                    "etag": _string(data, "etag"),
                    "revision": appointment.revision + 1,
                    "last_action_id": action.id,
                }
            )
        return ConnectorResult(
            operation=operation, status="SUCCEEDED", data=appointment.public()
        ), appointment

    async def _queue_communications(
        self,
        repository: AppointmentRepository,
        config: AppointmentsConfig,
        appointment: Appointment,
        action: ActionRecord,
    ) -> None:
        outbox = OutboxService(repository.session)
        kind = (
            "cancellation_request"
            if appointment.status == "CANCELLATION_REQUESTED"
            else "confirmation"
        )
        messages = [(kind, self.now())]
        reminder_at = appointment.start - timedelta(
            minutes=config.communications.reminder_minutes_before
        )
        if appointment.status == "BOOKED" and reminder_at > self.now():
            messages.append(("reminder", reminder_at))
        if appointment.revision > 1:
            previous = (
                f"appointments.notify:{appointment.id}:{appointment.revision - 1}:"
            )
            await repository.session.execute(
                text(
                    "UPDATE public.outbound_messages SET status = 'BLOCKED', provider_error_code = 'appointment_revision_superseded', updated_at = now(), status_history = status_history || jsonb_build_array(jsonb_build_object('status', 'BLOCKED', 'occurred_at', now(), 'source', 'appointments')) WHERE tenant_id = :tenant AND status = 'PREPARED' AND idempotency_key IN (:confirmation, :reminder, :cancellation)"
                ),
                {
                    "tenant": self.context.tenant_id,
                    "confirmation": previous + "confirmation",
                    "reminder": previous + "reminder",
                    "cancellation": previous + "cancellation_request",
                },
            )
        if action.approval_required and kind == "cancellation_request":
            # The approval coordinator owns this one customer result; still
            # suppress obsolete reminders above, but do not send a second notice.
            return
        for message_kind, due in messages:
            await outbox.enqueue(
                context=self.context,
                idempotency_key=f"appointments.notify:{appointment.id}:{appointment.revision}:{message_kind}",
                topic="appointments.notify",
                payload={
                    "aggregate_id": str(appointment.id),
                    "appointment_id": str(appointment.id),
                    "revision": appointment.revision,
                    "kind": message_kind,
                    "action_id": str(action.id),
                },
                available_at=due,
            )


class AppointmentActionConnector:
    """ActionService adapter; direct model calls cannot bypass revalidation gates."""

    def __init__(self, service: AppointmentsService) -> None:
        self.service = service
        self._permits: dict[str, ActionRecord] = {}

    def is_safe_read(self, operation: str) -> bool:
        return operation in DEFINITIONS and DEFINITIONS[operation].risk == "LOW"

    async def revalidate(self, action: ActionRecord) -> PreconditionDecision:
        self._permits.pop(str(action.id), None)
        definition = DEFINITIONS.get(action.action_type)
        valid = (
            definition is not None
            and action.tenant_id == self.service.context.tenant_id
            and action.capability == "appointments"
            and action.connector_name == "google_calendar"
        )
        if definition is not None:
            valid = (
                valid
                and action.risk == definition.risk
                and action.achieved_identity_level
                >= max(
                    action.required_identity_level, definition.required_identity_level
                )
                and (
                    not definition.requires_confirmation or action.confirmation_required
                )
                and (not definition.requires_approval or action.approval_required)
            )
        ready = action.state == "CONFIRMED" and not action.approval_required
        approved = (
            action.state == "AWAITING_APPROVAL"
            and action.approval_required
            and bool(action.approval_reference)
            and action.approved_at is not None
        )
        valid = (
            valid
            and (ready or approved)
            and (
                not action.confirmation_required
                or action.confirmation_digest is not None
                and action.confirmed_at is not None
            )
        )
        if definition is not None:
            valid = (
                valid
                and action_gate(
                    action.action_type,
                    identity_level=int(action.achieved_identity_level),
                    confirmed=action.confirmed_at is not None
                    and action.confirmation_digest is not None,
                    approved=approved,
                )
                == "READY"
            )
        if valid:
            async with self.service.transaction() as repository:
                config = await repository.config()
            valid = action.connector_binding_id == config.binding_id
            if valid and action.approval_required:
                try:
                    async with self.service.transaction() as repository:
                        appointment = await repository.get(
                            UUID(str(action.parameters["appointment_id"])),
                            customer_ref=action.customer_ref,
                        )
                    live = await self.service._call(
                        config,
                        "calendar.get_event",
                        {"event_id": appointment.external_event_id},
                    )
                    if live.get("status") == "cancelled":
                        return PreconditionDecision(
                            valid=False, reason_code="appointment_already_cancelled"
                        )
                    valid = (
                        live.get("etag") == appointment.etag
                        and appointment.status == "BOOKED"
                        and action.parameters.get("configuration_digest")
                        == configuration_digest(config)
                    )
                except (AppointmentUnavailable, KeyError, ValueError):
                    valid = False
        if valid:
            self._permits[str(action.id)] = action
        return PreconditionDecision(
            valid=bool(valid),
            reason_code="ready" if valid else "appointment_action_not_authorized",
        )

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        action = self._permits.get(request.idempotency_key or "")
        if (
            action is None
            or action.tenant_id != request.tenant_id
            or action.connector_binding_id != request.binding_id
            or action.action_type != request.operation
            or action.parameter_digest
            != NormalizedParameters.from_value(request.arguments).digest
        ):
            return ConnectorResult(
                operation=request.operation,
                status="REJECTED",
                error_code="appointment_action_not_authorized",
            )
        if not self.is_safe_read(request.operation):
            self._permits.pop(str(action.id), None)
        return await self.service._execute_authorized(action)


def _string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        # A provider mutation may have succeeded; this must stay UNCERTAIN.
        raise RuntimeError("invalid_calendar_result")
    return value


def _event_interval(event: dict[str, object], timezone: str) -> BusyInterval:
    values: dict[str, datetime] = {}
    for edge in ("start", "end"):
        value = event.get(edge)
        if not isinstance(value, dict):
            raise AppointmentUnavailable("availability_unknown")
        if isinstance(value.get("dateTime"), str):
            instant = datetime.fromisoformat(value["dateTime"])
            if instant.tzinfo is None:
                raise AppointmentUnavailable("availability_unknown")
        elif isinstance(value.get("date"), str):
            instant = datetime.combine(
                date.fromisoformat(value["date"]), time.min, tzinfo=ZoneInfo(timezone)
            )
        else:
            raise AppointmentUnavailable("availability_unknown")
        values[edge] = instant.astimezone(UTC)
    return BusyInterval.model_validate(values)
