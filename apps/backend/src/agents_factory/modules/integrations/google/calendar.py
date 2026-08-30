from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import ClassVar, Self
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.google.auth import (
    CALENDAR_BUSY,
    CALENDAR_READ,
    CALENDAR_WRITE,
)
from agents_factory.modules.integrations.google.base import (
    GoogleConnector,
    GoogleFailure,
    InputModel,
    ResourceId,
    manifest,
    response_string,
)


class CalendarWindow(InputModel):
    start: AwareDatetime
    end: AwareDatetime
    timezone: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if not self.start < self.end <= self.start + timedelta(days=31):
            raise ValueError("invalid calendar window")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("invalid timezone") from None
        return self

    def time(self, value: AwareDatetime) -> dict[str, str]:
        return {
            "dateTime": value.astimezone(ZoneInfo(self.timezone)).isoformat(),
            "timeZone": self.timezone,
        }


class EventId(InputModel):
    event_id: ResourceId


class CreateEvent(CalendarWindow):
    summary: str = Field(min_length=1, max_length=300)


class RescheduleEvent(CalendarWindow):
    event_id: ResourceId
    etag: str = Field(min_length=1, max_length=300, pattern=r"^[^\r\n]+$")


class CalendarResource(InputModel):
    calendar_id: ResourceId


class GoogleCalendarConnector(GoogleConnector[CalendarResource]):
    manifest = manifest(
        "google_calendar",
        "Google Calendar",
        (
            "calendar.check_availability",
            "calendar.list_events",
            "calendar.get_event",
            "calendar.create_event",
            "calendar.reschedule_event",
        ),
        "calendar.GoogleCalendarConnector",
    )
    operation_scopes: ClassVar[dict[str, frozenset[str]]] = {
        "calendar.check_availability": frozenset({CALENDAR_BUSY}),
        "calendar.list_events": frozenset({CALENDAR_READ, CALENDAR_WRITE}),
        "calendar.get_event": frozenset({CALENDAR_READ, CALENDAR_WRITE}),
        "calendar.create_event": frozenset({CALENDAR_WRITE}),
        "calendar.reschedule_event": frozenset({CALENDAR_WRITE}),
    }
    write_operations = frozenset({"calendar.create_event", "calendar.reschedule_event"})

    async def _execute(self, request: ConnectorRequest) -> dict[str, object]:
        root = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            + quote(self.resource.calendar_id, safe="")
            + "/events"
        )
        operation = request.operation
        if operation == "calendar.get_event":
            args = EventId.model_validate(request.arguments)
            return _event(
                await self.http.json(
                    "GET",
                    root + "/" + quote(args.event_id, safe=""),
                    access=self.access,
                )
            )
        if operation == "calendar.create_event":
            create = CreateEvent.model_validate(request.arguments)
            # Calendar's provider-native event ID makes retries reconcilable.
            action_id = hashlib.sha256(
                f"{request.tenant_id}:{request.binding_id}:{request.idempotency_key}".encode()
            ).hexdigest()
            digest = hashlib.sha256(create.model_dump_json().encode()).hexdigest()
            body = {
                "id": action_id,
                "summary": create.summary,
                "start": create.time(create.start),
                "end": create.time(create.end),
                "extendedProperties": {
                    "private": {"action_id": action_id, "request_digest": digest}
                },
            }
            try:
                payload = await self.http.json(
                    "POST", root, access=self.access, body=body, write=True
                )
            except GoogleFailure as error:
                if error.code != "conflict":
                    raise
                payload = await self.http.json(
                    "GET", root + "/" + action_id, access=self.access
                )
                if payload.get("extendedProperties") != body["extendedProperties"]:
                    raise GoogleFailure("idempotency_conflict") from None
            return _event(payload, write=True)
        if operation == "calendar.reschedule_event":
            update = RescheduleEvent.model_validate(request.arguments)
            payload = await self.http.json(
                "PATCH",
                root + "/" + quote(update.event_id, safe=""),
                access=self.access,
                headers={"If-Match": update.etag},
                body={
                    "start": update.time(update.start),
                    "end": update.time(update.end),
                },
                write=True,
            )
            return _event(payload, write=True)
        window = CalendarWindow.model_validate(request.arguments)
        if operation == "calendar.check_availability":
            payload = await self.http.json(
                "POST",
                "https://www.googleapis.com/calendar/v3/freeBusy",
                access=self.access,
                body={
                    "timeMin": window.start.isoformat(),
                    "timeMax": window.end.isoformat(),
                    "timeZone": window.timezone,
                    "items": [{"id": self.resource.calendar_id}],
                },
            )
            calendars = payload.get("calendars")
            calendar = (
                calendars.get(self.resource.calendar_id)
                if isinstance(calendars, dict)
                else None
            )
            if (
                not isinstance(calendar, dict)
                or calendar.get("errors")
                or not isinstance(calendar.get("busy"), list)
            ):
                raise GoogleFailure("availability_unknown")
            busy: list[dict[str, str]] = []
            for period in calendar["busy"]:
                if not isinstance(period, dict):
                    raise GoogleFailure("invalid_response")
                try:
                    interval = CalendarWindow.model_validate(
                        {**period, "timezone": window.timezone}
                    )
                except ValueError:
                    raise GoogleFailure("invalid_response") from None
                busy.append(
                    {
                        "start": interval.start.isoformat(),
                        "end": interval.end.isoformat(),
                    }
                )
            return {"busy": busy, "timezone": window.timezone}
        events: list[dict[str, object]] = []
        params = {
            "timeMin": window.start.isoformat(),
            "timeMax": window.end.isoformat(),
            "timeZone": window.timezone,
            "singleEvents": "true",
            "maxResults": "250",
            "orderBy": "startTime",
        }
        seen: set[str] = set()
        for _ in range(20):
            page = await self.http.json("GET", root, access=self.access, params=params)
            items = page.get("items", [])
            if not isinstance(items, list):
                raise GoogleFailure("invalid_response")
            for item in items:
                if not isinstance(item, dict):
                    raise GoogleFailure("invalid_response")
                events.append(_event(item))
            next_page = page.get("nextPageToken")
            if next_page is None:
                return {"events": events}
            if not isinstance(next_page, str) or not next_page or next_page in seen:
                raise GoogleFailure("invalid_response")
            seen.add(next_page)
            params["pageToken"] = next_page
        raise GoogleFailure("pagination_limit")


def _event(payload: dict[str, object], *, write: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "event_id": response_string(payload, "id", write=write),
        "etag": response_string(payload, "etag", write=write),
    }
    # Select fields; never leak raw provider diagnostics or unrelated event data.
    for key in ("status", "summary", "start", "end"):
        if key in payload:
            result[key] = payload[key]
    return result
