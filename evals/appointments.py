from __future__ import annotations

from agents_factory.modules.capabilities.appointments.manifest import action_gate
from evals.case_schema import AppointmentProbe


def observe_appointment(probe: AppointmentProbe) -> str:
    # Execute the same code-owned gate used by the real ActionConnector; do not
    # grade an expected fake answer as though it were a safety decision.
    return action_gate(
        probe.operation,
        identity_level=probe.identity_level,
        confirmed=probe.confirmed,
        approved=probe.approved,
    )
