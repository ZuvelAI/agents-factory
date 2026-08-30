from __future__ import annotations

from typing import Protocol
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.cases.contracts import CaseIntake
from agents_factory.modules.capabilities.orders.models import IssueDraft


class EvidenceAccess(Protocol):
    async def allowed(
        self, *, context: TenantContext, customer_ref: str, evidence_id: UUID
    ) -> bool:
        """Task 27 supplies private evidence references; URLs never prove access."""
        ...


class DenyEvidence:
    async def allowed(
        self, *, context: TenantContext, customer_ref: str, evidence_id: UUID
    ) -> bool:
        return False


class IssueNeedsInformation(ValueError):
    def __init__(self, fields: tuple[str, ...]) -> None:
        self.fields = fields
        super().__init__("issue_needs_information")


def missing_information(draft: IssueDraft) -> tuple[str, ...]:
    missing = []
    if not draft.description or not draft.description.strip():
        missing.append("description")
    if not draft.order_id and not draft.purchase_reference:
        missing.append("order_id_or_purchase_reference")
    if draft.issue_type in {"wrong_product", "damaged_product"} and not draft.item_ids:
        missing.append("item_ids")
    if draft.issue_type == "damaged_product" and not draft.evidence_ids:
        missing.append("evidence_ids")
    return tuple(missing)


def case_intake(
    *,
    context: TenantContext,
    conversation_id: UUID,
    customer_ref: str,
    binding_id: UUID,
    action_id: UUID,
    draft: IssueDraft,
    order_verified: bool,
) -> CaseIntake:
    missing = missing_information(draft)
    if missing:
        raise IssueNeedsInformation(missing)
    assert draft.description is not None
    resource = draft.order_id or draft.purchase_reference
    assert resource is not None
    key = NormalizedParameters.from_value(
        {
            "tenant_id": str(context.tenant_id),
            "customer_ref": customer_ref,
            "capability": "orders",
            "issue_type": draft.issue_type,
            "resource_id": f"{binding_id}:{resource}",
        }
    ).digest
    return CaseIntake(
        tenant_id=context.tenant_id,
        customer_ref=customer_ref,
        conversation_id=conversation_id,
        issue_type=draft.issue_type,
        binding_id=binding_id,
        resource_id=resource,
        order_verified=order_verified,
        description=draft.description,
        item_ids=draft.item_ids,
        evidence_ids=draft.evidence_ids,
        incident_date=draft.incident_date,
        requested_resolution=draft.requested_resolution,
        idempotency_key=action_id,
        deduplication_key=key,
    )
