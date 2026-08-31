from datetime import UTC, datetime, time

import pytest

from agents_factory.modules.handoffs.models import (
    HandoffConfiguration,
    HandoffReason,
    SupportWindow,
)
from agents_factory.modules.handoffs.policy import (
    escalation_reason,
    waiting_copy,
    within_support_hours,
)
from agents_factory.modules.handoffs.surfaces import HumanSurfaceRegistry


def test_only_clear_requests_and_backend_risks_trigger():
    for message in (
        "necesito ayuda",
        "esto es frustrante",
        "PENDING_APPROVAL",
        "no quiero hablar con un humano",
    ):
        assert escalation_reason(customer_text=message) is None
    for message in (
        "Quiero hablar con una persona",
        "Por favor, pásame con un asesor",
        "Please talk to a human",
    ):
        assert (
            escalation_reason(customer_text=message) == HandoffReason.EXPLICIT_REQUEST
        )
    assert (
        escalation_reason(mandatory_policy=True) == HandoffReason.MANDATORY_ESCALATION
    )
    assert (
        escalation_reason(repeated_integration_failure=True)
        == HandoffReason.REPEATED_INTEGRATION_FAILURE
    )
    assert (
        escalation_reason(consequential_action_unresolved=True)
        == HandoffReason.CONSEQUENTIAL_ACTION_UNRESOLVED
    )


def test_support_hours_timezone_and_no_online_promise():
    config = HandoffConfiguration(
        timezone="America/Bogota",
        support_hours=(SupportWindow(weekday=0, start=time(9), end=time(17)),),
    )
    assert config.inactivity_hours == 12
    opened = datetime(2026, 8, 31, 15, tzinfo=UTC)
    closed = datetime(2026, 8, 31, 23, tzinfo=UTC)
    assert within_support_hours(config, opened)
    assert not within_support_hours(config, closed)
    assert "no confirma" in waiting_copy(config, opened)
    assert "fuera del horario" in waiting_copy(config, closed)
    with pytest.raises(ValueError):
        HandoffConfiguration(enabled=True)
    with pytest.raises(ValueError):
        HandoffConfiguration(timezone="invented/timezone")


def test_no_surface_is_installed_implicitly():
    from agents_factory.modules.handoffs.models import (
        HandoffError,
        HumanResponseSurface,
        SurfaceBinding,
    )

    with pytest.raises(HandoffError):
        HumanSurfaceRegistry().adapter(
            SurfaceBinding(
                surface=HumanResponseSurface.EXTERNAL_INBOX,
                adapter="unknown",
                binding_id="inbox",
            )
        )
