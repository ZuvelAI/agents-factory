import hashlib
from uuid import UUID

from agents_factory.modules.actions.models import NormalizedParameters


def case_key(
    tenant_id: UUID,
    customer_ref: str,
    capability: str,
    issue_type: str,
    binding_id: UUID,
    resource_id: str,
) -> str:
    # Preserve the already-approved Orders and Returns & Claims contracts.
    fields: dict[str, object] = {
        "tenant_id": str(tenant_id),
        "customer_ref": customer_ref,
        "capability": capability,
        "issue_type": issue_type,
        "resource_id": f"{binding_id}:{resource_id}"
        if capability == "orders"
        else resource_id,
    }
    if capability == "returns_claims":
        fields["binding_id"] = str(binding_id)
    return NormalizedParameters.from_value(fields).digest


def lock_key(tenant_id: UUID, namespace: str, value: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"cases:{tenant_id}:{namespace}:{value}".encode()).digest()[:8],
        "big",
        signed=True,
    )
