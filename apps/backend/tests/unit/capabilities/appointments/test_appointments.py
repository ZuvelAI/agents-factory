from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from apps.backend.tests.appointments_support import NOW, configuration
from agents_factory.modules.capabilities.appointments.availability import (
    available_slots,
    candidate_slot,
    local_instants,
)
from agents_factory.modules.capabilities.appointments.manifest import (
    APPOINTMENTS_MANIFEST,
    action_gate,
)
from agents_factory.modules.capabilities.appointments.models import (
    AppointmentsConfig,
    BusyInterval,
)
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY
from agents_factory.modules.capabilities.service import (
    CapabilityService,
    AgentSpecManifestError,
)
from agents_factory.modules.integrations.registry import V1_CONNECTOR_CATALOG


def test_availability_hours_buffers_lead_time_closed_dates_and_no_holds() -> None:
    config = configuration()
    day = date(2026, 9, 1)
    assert (
        candidate_slot(
            config, config.services[0], datetime(2026, 9, 1, 14, tzinfo=UTC), now=NOW
        )
        is None
    )
    occupied = (BusyInterval(start="2026-09-01T15:00:00Z", end="2026-09-01T16:00:00Z"),)
    slots = available_slots(config, "consultation", day, now=NOW, occupied=occupied)
    assert slots[0].start == datetime(2026, 9, 1, 14, 15, tzinfo=UTC)
    assert all(
        slot.busy_end <= occupied[0].start or slot.busy_start >= occupied[0].end
        for slot in slots
    )
    assert all((slot.end - slot.start).total_seconds() == 1800 for slot in slots)
    assert (
        available_slots(config, "consultation", day, now=NOW, occupied=occupied)
        == slots
    )
    assert (
        available_slots(
            configuration(closed_dates=[day]), "consultation", day, now=NOW, occupied=()
        )
        == ()
    )
    assert (
        available_slots(
            configuration(lead_minutes=1440), "consultation", day, now=NOW, occupied=()
        )
        == ()
    )
    with pytest.raises(ValidationError):
        AppointmentsConfig.model_validate(
            {
                **config.model_dump(mode="json"),
                "simultaneous_resources": ["room", "equipment"],
            }
        )


def test_timezone_dst_gap_fold_and_elapsed_duration() -> None:
    zone = ZoneInfo("America/New_York")
    from datetime import time

    assert local_instants(date(2026, 3, 8), time(2, 30), zone) == ()
    folded = local_instants(date(2026, 11, 1), time(1, 30), zone)
    assert len(folded) == 2 and (folded[1] - folded[0]).total_seconds() == 3600
    config = configuration(
        timezone="America/New_York",
        services=[
            {"id": "consultation", "name": "Consultation", "duration_minutes": 30}
        ],
        working_hours=[{"weekday": 6, "start": "00:00", "end": "05:00"}],
        lead_minutes=0,
    )
    slots = available_slots(
        config,
        "consultation",
        date(2026, 3, 8),
        now=datetime(2026, 3, 7, tzinfo=UTC),
        occupied=(),
    )
    assert all(slot.start.astimezone(zone).hour != 2 for slot in slots)
    assert all((slot.end - slot.start).total_seconds() == 1800 for slot in slots)


def test_policy_matrix_and_capability_to_primitive_binding() -> None:
    from apps.backend.tests.unit.integrations.test_operation_gating import spec
    from agents_factory.modules.agent_factory.models import (
        ConnectorBinding,
        VersionReference,
    )
    from apps.backend.tests.appointments_support import BINDING

    assert V1_CAPABILITY_REGISTRY.get("appointments", "1.0.0") == APPOINTMENTS_MANIFEST
    assert [
        (
            action.risk,
            action.required_identity_level,
            action.requires_confirmation,
            action.requires_approval,
        )
        for action in APPOINTMENTS_MANIFEST.actions
    ] == [
        ("LOW", 0, False, False),
        ("MEDIUM", 1, True, False),
        ("LOW", 1, False, False),
        ("MEDIUM", 2, True, False),
        ("HIGH", 2, True, True),
    ]
    assert (
        action_gate(
            "appointments.create_appointment",
            identity_level=1,
            confirmed=False,
            approved=False,
        )
        == "CONFIRMATION_REQUIRED"
    )
    assert (
        action_gate(
            "appointments.reschedule_appointment",
            identity_level=1,
            confirmed=True,
            approved=False,
        )
        == "IDENTITY_REQUIRED"
    )
    assert (
        action_gate(
            "appointments.request_cancellation",
            identity_level=2,
            confirmed=True,
            approved=False,
        )
        == "APPROVAL_REQUIRED"
    )
    original = spec(bound_operations=("orders.get_status",))
    binding = ConnectorBinding(
        binding_id=BINDING,
        connector="google_calendar",
        connector_version="1.0.0",
        operations=("calendar.check_availability", "calendar.create_event"),
    )
    amended = original.model_copy(
        update={
            "configuration": original.configuration.model_copy(
                update={
                    "capabilities": (
                        VersionReference(name="appointments", version="1.0.0"),
                    ),
                    "permitted_tools": ("appointments.create_appointment",),
                    "permitted_actions": ("appointments.create_appointment",),
                    "connector_bindings": (binding,),
                }
            )
        }
    )
    service = CapabilityService(
        capabilities=V1_CAPABILITY_REGISTRY, connectors=V1_CONNECTOR_CATALOG
    )
    service.validate_agent_spec(amended)
    broken = amended.model_copy(
        update={
            "configuration": amended.configuration.model_copy(
                update={
                    "connector_bindings": (
                        binding.model_copy(
                            update={"operations": ("calendar.create_event",)}
                        ),
                    )
                }
            )
        }
    )
    with pytest.raises(AgentSpecManifestError, match="not supported"):
        service.validate_agent_spec(broken)


async def test_native_reschedule_carries_action_metadata_and_if_match() -> None:
    import hashlib
    import json
    import httpx
    from apps.backend.tests.contract.integrations.google.test_google_contracts import (
        credential,
        binding,
        request,
    )
    from agents_factory.modules.integrations.google.auth import CALENDAR_WRITE
    from agents_factory.modules.integrations.google.base import GoogleHTTP
    from agents_factory.modules.integrations.google.calendar import (
        CalendarResource,
        GoogleCalendarConnector,
    )

    bound = binding(("calendar.reschedule_event",))

    def provider(req: httpx.Request) -> httpx.Response:
        assert req.method == "PATCH" and req.headers["If-Match"] == '"v1"'
        private = json.loads(req.content)["extendedProperties"]["private"]
        assert (
            private["action_id"]
            == hashlib.sha256(
                f"{bound.tenant_id}:{bound.binding_id}:action-fixture".encode()
            ).hexdigest()
        )
        assert len(private["request_digest"]) == 64
        return httpx.Response(200, json={"id": "event-fixture", "etag": '"v2"'})

    adapter = GoogleCalendarConnector(
        binding=bound,
        resource=CalendarResource(calendar_id="primary"),
        credential=credential((CALENDAR_WRITE,)),
        http=GoogleHTTP(httpx.MockTransport(provider)),
    )
    result = await adapter.execute(
        request(
            bound,
            "calendar.reschedule_event",
            {
                "event_id": "event-fixture",
                "etag": '"v1"',
                "start": "2026-09-01T16:15:00Z",
                "end": "2026-09-01T16:45:00Z",
                "timezone": "America/Bogota",
            },
        )
    )
    assert result.status == "SUCCEEDED"
