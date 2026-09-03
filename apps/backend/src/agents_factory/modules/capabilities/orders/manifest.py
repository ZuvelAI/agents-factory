from agents_factory.modules.capabilities.contracts import (
    ActionDefinition,
    CapabilityManifest,
)
from agents_factory.modules.capabilities.orders.models import INPUTS, IssueDraft
from agents_factory.modules.integrations.orders import READS, WRITES


ORDERS_MANIFEST = CapabilityManifest(
    stable_name="orders",
    version="1.0.0",
    intents=(
        "find_order",
        "order_status",
        "order_tracking",
        "order_items",
        "order_delivery",
        "update_order",
        "request_cancellation",
        "missing_order",
        "wrong_product",
        "damaged_product",
        "delivery_delay",
        "create_claim",
    ),
    workflow=(
        "resolve_trusted_customer",
        "verify_identity_and_owner",
        "read_order",
        "collect_issue_information",
        "confirm_exact_change",
        "approve_high_risk",
        "revalidate",
        "execute_once",
        "report_verified_status",
    ),
    business_schemas={"issue": IssueDraft.model_json_schema()},
    actions=tuple(
        ActionDefinition.model_validate(
            {
                "name": op,
                "description": op.partition(".")[2].replace("_", " "),
                "input_schema": model.model_json_schema(),
                "output_schema": {"type": "object"},
                "risk": "LOW"
                if op in READS
                else "HIGH"
                if op == WRITES[3]
                else "MEDIUM",
                "required_identity_level": 1
                if op in READS or op == "orders.create_claim"
                else 2,
                "requires_confirmation": op not in READS,
                "requires_approval": op == WRITES[3],
                "required_connector_operations": (READS[0],)
                if op == "orders.create_claim"
                else (op, READS[1])
                if op in WRITES
                else (op,),
                "failure_behavior": "Do not guess an order state, repeat an uncertain write, or promise cancellation/refund/claim acceptance.",
                "handoff_behavior": "Request missing issue information or offer backoffice review; only report a case after a matching Cases receipt.",
                "eval_case_ids": (op,),
            }
        )
        for op, model in INPUTS.items()
    ),
)
DEFINITIONS = {definition.name: definition for definition in ORDERS_MANIFEST.actions}


def action_gate(
    operation: str,
    *,
    identity_level: int,
    confirmed: bool,
    approved: bool,
    supported: bool = True,
) -> str:
    if not supported or operation not in DEFINITIONS:
        return "UNAVAILABLE"
    definition = DEFINITIONS[operation]
    if identity_level < definition.required_identity_level:
        return "IDENTITY_REQUIRED"
    if definition.requires_confirmation and not confirmed:
        return "CONFIRMATION_REQUIRED"
    if definition.requires_approval and not approved:
        return "APPROVAL_REQUIRED"
    return "READY"
