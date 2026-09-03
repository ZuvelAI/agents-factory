from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from agents_factory.modules.capabilities.appointments.models import AppointmentsConfig
from agents_factory.modules.integrations.contracts import (
    ConnectorRequest,
    ConnectorResult,
)


NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
BINDING = UUID("00000000-0000-4000-8000-000000002401")
CONNECTION = UUID("00000000-0000-4000-8000-000000002402")
ACCOUNT = UUID("00000000-0000-4000-8000-000000002403")


def configuration(**changes: object) -> AppointmentsConfig:
    return AppointmentsConfig.model_validate(
        {
            "binding_id": BINDING,
            "connection_id": CONNECTION,
            "calendar_id": "primary",
            "timezone": "America/Bogota",
            "main_professional": {"id": "professional", "name": "Professional"},
            "location": {"id": "office", "name": "Office"},
            "services": [
                {
                    "id": "consultation",
                    "name": "Consultation",
                    "duration_minutes": 30,
                    "buffer_before_minutes": 15,
                    "buffer_after_minutes": 15,
                }
            ],
            "working_hours": [
                {"weekday": day, "start": "09:00", "end": "17:00"} for day in range(5)
            ],
            "lead_minutes": 60,
            "approval_route_ref": "appointment-approvals",
            "communications": {
                "whatsapp_account_id": ACCOUNT,
                "language": "es_CO",
                "confirmation_template": "appointment_confirmation",
                "reminder_template": "appointment_reminder",
                "cancellation_request_template": "appointment_cancellation",
                "reminder_minutes_before": 60,
            },
            **changes,
        }
    )


class FakeCalendar:
    def __init__(self) -> None:
        self.events: dict[str, dict[str, object]] = {}
        self.writes = 0
        self.fail_after_write = False
        self.calls: list[str] = []

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        self.calls.append(request.operation)
        args, operation = request.arguments, request.operation
        if operation == "calendar.check_availability":
            busy = [
                {"start": event["start"]["dateTime"], "end": event["end"]["dateTime"]}
                for event in self.events.values()
            ]
            return ConnectorResult(
                operation=operation, status="SUCCEEDED", data={"busy": busy}
            )
        if operation == "calendar.list_events":
            return ConnectorResult(
                operation=operation,
                status="SUCCEEDED",
                data={"events": list(self.events.values())},
            )
        if operation == "calendar.get_event":
            return ConnectorResult(
                operation=operation,
                status="SUCCEEDED",
                data=self.events[str(args["event_id"])],
            )
        self.writes += 1
        if operation == "calendar.create_event":
            event_id = "event-" + str(request.idempotency_key)
        else:
            event_id = str(args["event_id"])
            assert args["etag"] == self.events[event_id]["etag"]
        event = {
            "event_id": event_id,
            "etag": f'"v{self.writes}"',
            "status": "confirmed",
            "start": {"dateTime": args["start"]},
            "end": {"dateTime": args["end"]},
        }
        self.events[event_id] = event
        if self.fail_after_write:
            return ConnectorResult(
                operation=operation, status="UNCERTAIN", error_code="provider_timeout"
            )
        return ConnectorResult(operation=operation, status="SUCCEEDED", data=event)
