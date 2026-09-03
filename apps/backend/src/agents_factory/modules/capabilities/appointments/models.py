from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


Name = Annotated[str, Field(min_length=1, max_length=200)]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")]
Operation = Literal[
    "appointments.check_availability",
    "appointments.create_appointment",
    "appointments.get_appointment",
    "appointments.reschedule_appointment",
    "appointments.request_cancellation",
]


class Service(Model):
    id: Identifier
    name: Name
    duration_minutes: int = Field(ge=5, le=480)
    buffer_before_minutes: int = Field(default=0, ge=0, le=120)
    buffer_after_minutes: int = Field(default=0, ge=0, le=120)


class Resource(Model):
    id: Identifier
    name: Name


class WorkingHours(Model):
    weekday: int = Field(ge=0, le=6)
    start: time
    end: time

    @model_validator(mode="after")
    def valid_hours(self) -> Self:
        if (
            self.start >= self.end
            or self.start.tzinfo
            or self.end.tzinfo
            or self.start.second
            or self.end.second
            or self.start.microsecond
            or self.end.microsecond
        ):
            raise ValueError(
                "working hours must be same-day, minute-precision local times"
            )
        return self


class Communications(Model):
    whatsapp_account_id: UUID
    language: str = Field(pattern=r"^(es|en)(_[A-Z]{2})?$")
    confirmation_template: Identifier
    reminder_template: Identifier
    cancellation_request_template: Identifier
    reminder_minutes_before: int = Field(default=1440, ge=1, le=43200)


class AppointmentsConfig(Model):
    binding_id: UUID
    connection_id: UUID
    calendar_id: str = Field(
        min_length=1, max_length=254, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_@.+\-]*$"
    )
    timezone: str = Field(min_length=1, max_length=100)
    main_professional: Resource
    location: Resource
    services: tuple[Service, ...] = Field(min_length=1, max_length=100)
    working_hours: tuple[WorkingHours, ...] = Field(min_length=1, max_length=28)
    closed_dates: frozenset[date] = frozenset()
    lead_minutes: int = Field(default=60, ge=0, le=43200)
    booking_horizon_days: int = Field(default=90, ge=1, le=365)
    slot_step_minutes: int = Field(default=15, ge=5, le=120)
    approval_route_ref: Name
    communications: Communications

    @model_validator(mode="after")
    def v1_configuration(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("invalid timezone") from None
        if len({service.id for service in self.services}) != len(self.services):
            raise ValueError("duplicate service")
        windows = sorted(
            self.working_hours, key=lambda item: (item.weekday, item.start)
        )
        if any(
            a.weekday == b.weekday and a.end > b.start
            for a, b in zip(windows, windows[1:])
        ):
            raise ValueError("working hours overlap")
        return self

    def service(self, service_id: str) -> Service:
        for service in self.services:
            if service.id == service_id:
                return service
        raise ValueError("service_unavailable")


class CheckAvailability(Model):
    service_id: Identifier
    day: date


class CreateAppointment(Model):
    service_id: Identifier
    professional_id: Identifier
    location_id: Identifier
    start: AwareDatetime


class GetAppointment(Model):
    appointment_id: UUID


class RescheduleAppointment(GetAppointment):
    start: AwareDatetime


class RequestCancellation(GetAppointment):
    reason: str = Field(min_length=1, max_length=1000)


class Appointment(Model):
    id: UUID
    tenant_id: UUID
    customer_ref: str
    conversation_id: UUID
    service_id: str
    professional_id: str
    location_id: str
    start: AwareDatetime
    end: AwareDatetime
    busy_start: AwareDatetime
    busy_end: AwareDatetime
    external_event_id: str
    etag: str
    status: Literal["BOOKED", "CANCELLATION_REQUESTED"] = "BOOKED"
    revision: int = Field(default=1, ge=1)
    last_action_id: UUID

    def public(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            exclude={
                "tenant_id",
                "customer_ref",
                "conversation_id",
                "busy_start",
                "busy_end",
                "last_action_id",
                "etag",
                "external_event_id",
            },
        )


class BusyInterval(Model):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("invalid busy interval")
        return self


class Slot(Model):
    start: datetime
    end: datetime
    busy_start: datetime
    busy_end: datetime


INPUTS: dict[str, type[Model]] = {
    "appointments.check_availability": CheckAvailability,
    "appointments.create_appointment": CreateAppointment,
    "appointments.get_appointment": GetAppointment,
    "appointments.reschedule_appointment": RescheduleAppointment,
    "appointments.request_cancellation": RequestCancellation,
}
