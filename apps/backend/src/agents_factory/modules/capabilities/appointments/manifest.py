from __future__ import annotations

from agents_factory.modules.capabilities.appointments.models import Appointment, INPUTS
from agents_factory.modules.capabilities.contracts import (
    ActionDefinition,
    CapabilityManifest,
)


ACTION_RULES = (
    ("check_availability", "LOW", 0, ("calendar.check_availability",)),
    (
        "create_appointment",
        "MEDIUM",
        1,
        ("calendar.check_availability", "calendar.create_event"),
    ),
    ("get_appointment", "LOW", 1, ("calendar.get_event",)),
    (
        "reschedule_appointment",
        "MEDIUM",
        2,
        ("calendar.list_events", "calendar.get_event", "calendar.reschedule_event"),
    ),
    ("request_cancellation", "HIGH", 2, ("calendar.get_event",)),
)

APPOINTMENTS_MANIFEST = CapabilityManifest(
    stable_name="appointments",
    version="1.0.0",
    intents=(
        "check_availability",
        "book_appointment",
        "view_appointment",
        "reschedule_appointment",
        "request_cancellation",
    ),
    workflow=(
        "identify_service_resource",
        "verify_identity_and_ownership",
        "request_action",
        "confirm_exact_parameters",
        "obtain_approval_if_required",
        "revalidate_availability",
        "execute_once",
        "notify",
    ),
    business_schemas={"appointment": Appointment.model_json_schema()},
    actions=tuple(
        ActionDefinition.model_validate(
            {
                "name": "appointments." + name,
                "description": name.replace("_", " "),
                "input_schema": INPUTS["appointments." + name].model_json_schema(),
                "output_schema": {"type": "object"},
                "risk": risk,
                "required_identity_level": level,
                "requires_confirmation": risk != "LOW",
                "requires_approval": risk == "HIGH",
                "required_connector_operations": operations,
                "failure_behavior": "Do not invent availability or claim an unverified booking/cancellation.",
                "handoff_behavior": "Offer backoffice review for conflicts, unsupported resources or uncertain results.",
                "eval_case_ids": ("appointments." + name,),
            }
        )
        for name, risk, level, operations in ACTION_RULES
    ),
)

DEFINITIONS = {action.name: action for action in APPOINTMENTS_MANIFEST.actions}


def action_gate(
    operation: str, *, identity_level: int, confirmed: bool, approved: bool
) -> str:
    definition = DEFINITIONS[operation]
    if identity_level < definition.required_identity_level:
        return "IDENTITY_REQUIRED"
    if definition.requires_confirmation and not confirmed:
        return "CONFIRMATION_REQUIRED"
    if definition.requires_approval and not approved:
        return "APPROVAL_REQUIRED"
    return "READY"
