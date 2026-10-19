"""The only shipped internal prospect operations; not an external connector."""

from agents_factory.modules.capabilities.contracts import (
    ActionDefinition,
    CapabilityManifest,
)
from agents_factory.modules.runtime.contracts import AgentSpecSnapshot

from .models import LeadProposal

LEAD_CAPTURE_TOOLS = frozenset({"lead_capture.propose", "lead_capture.suppress"})
LEAD_CAPTURE_VERSION = "1.0.0"

LEAD_CAPTURE_MANIFEST = CapabilityManifest(
    stable_name="lead_capture",
    version=LEAD_CAPTURE_VERSION,
    intents=("commercial_interest", "capture_refusal"),
    workflow=(
        "identify_customer_evidence",
        "prepare_proposal",
        "validate_and_commit_with_turn",
    ),
    business_schemas={"proposal": LeadProposal.model_json_schema()},
    actions=tuple(
        ActionDefinition(
            name=name,
            description="Preparar una propuesta interna con evidencia del cliente; no confirma persistencia.",
            input_schema=LeadProposal.model_json_schema(),
            output_schema={
                "type": "object",
                "properties": {"status": {"const": "PREPARED"}},
            },
            risk="LOW",
            required_identity_level=0,
            requires_confirmation=False,
            requires_approval=False,
            failure_behavior="Rechazar datos no respaldados sin confirmar guardado.",
            handoff_behavior="Respetar control humano y negativa a registrar datos.",
            eval_case_ids=("lead_interest", "lead_no_interest", "lead_refusal"),
        )
        for name in sorted(LEAD_CAPTURE_TOOLS)
    ),
)


def lead_capture_enabled(snapshot: AgentSpecSnapshot) -> bool:
    return (
        snapshot.active
        and "lead_capture" in snapshot.active_capabilities
        and LEAD_CAPTURE_TOOLS <= snapshot.permitted_tools
    )
