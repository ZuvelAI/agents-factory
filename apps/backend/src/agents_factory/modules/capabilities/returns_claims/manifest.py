from agents_factory.modules.capabilities.contracts import (
    ActionDefinition,
    CapabilityManifest,
)
from agents_factory.modules.capabilities.returns_claims.models import (
    ISSUE_CLASSES,
    ClaimDraft,
    ClaimStatusInput,
    ClaimSubmission,
)


RETURNS_CLAIMS_MANIFEST = CapabilityManifest(
    stable_name="returns_claims",
    version="1.0.0",
    intents=ISSUE_CLASSES,
    workflow=(
        "identify",
        "classify",
        "collect_evidence",
        "validate_completeness_and_policy",
        "confirm_intake",
        "create_or_update_case",
        "backoffice_review",
        "communicate_verified_status_or_result",
    ),
    business_schemas={"claim": ClaimDraft.model_json_schema()},
    actions=tuple(
        ActionDefinition(
            name=operation,
            description=description,
            input_schema=model.model_json_schema(),
            output_schema={"type": "object"},
            risk="MEDIUM" if mutation else "LOW",
            required_identity_level=1,
            requires_confirmation=mutation,
            requires_approval=False,
            connector_requirement_mode="all_bindings" if mutation else "none",
            required_connector_operations=(
                "orders.get_status",
                "drive.store_evidence",
                "sheets.read_rows",
                "sheets.append_row",
                "sheets.update_row",
                "gmail.send_approval_notice",
            )
            if mutation
            else (),
            failure_behavior="Never approve a return, refund, issue credit, promise acceptance, or report an unpersisted case.",
            handoff_behavior="Collect missing information; policy/ownership ambiguity requires backoffice review. Requested resolution is not a decision.",
            eval_case_ids=("returns_claims.confirmation",)
            if mutation
            else ("returns_claims.status_identity",),
        )
        for operation, description, model, mutation in (
            (
                "returns_claims.create_or_update_case",
                "Submit the customer's claim for backoffice review, never approve its resolution.",
                ClaimSubmission,
                True,
            ),
            (
                "returns_claims.get_case_status",
                "Read only the customer's verified case status and human-recorded result.",
                ClaimStatusInput,
                False,
            ),
        )
    ),
)
DEFINITIONS = {
    definition.name: definition for definition in RETURNS_CLAIMS_MANIFEST.actions
}


def action_gate(
    operation: str, *, identity_level: int, confirmed: bool, supported: bool = True
) -> str:
    """Manifest minimums only; the Action engine enforces stronger tenant policy."""
    definition = DEFINITIONS.get(operation)
    if definition is None or not supported:
        return "UNAVAILABLE"
    if identity_level < definition.required_identity_level:
        return "IDENTITY_REQUIRED"
    if definition.requires_confirmation and not confirmed:
        return "CONFIRMATION_REQUIRED"
    return "READY"
