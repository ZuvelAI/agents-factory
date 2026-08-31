from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, get_args
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator

from agents_factory.modules.integrations.google.base import InputModel
from agents_factory.modules.knowledge.models import KnowledgeProvenance


IssueClass = Literal[
    "wrong_product",
    "damaged_product",
    "incomplete_order",
    "not_received",
    "late_delivery",
    "nonconformity",
    "return_request",
]
ISSUE_CLASSES: tuple[IssueClass, ...] = get_args(IssueClass)
RequiredField = Literal["item_ids", "incident_date", "purchase_date", "evidence_ids"]
Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ClaimDraft(InputModel):
    """Customer-supplied facts only. No tenant, owner, policy or decision flags."""

    issue_type: IssueClass | None = None
    order_id: Identifier | None = None
    purchase_reference: Identifier | None = None
    description: Description | None = None
    item_ids: tuple[Identifier, ...] = Field(default=(), max_length=50)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=20)
    incident_date: date | None = None
    purchase_date: date | None = None
    requested_resolution: Description | None = None
    evidence_unavailable_reason: Description | None = None

    @field_validator("item_ids")
    @classmethod
    def canonical_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @field_validator("evidence_ids")
    @classmethod
    def canonical_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(set(value), key=str))


class ClaimStatusInput(InputModel):
    case_id: UUID


class ClaimsBinding(InputModel):
    """Backend configuration pinned to the approved AgentSpec Knowledge version."""

    tenant_id: UUID
    binding_id: UUID
    knowledge_version_id: UUID
    knowledge_digest: Digest


class ApprovedClaimPolicy(InputModel):
    """Loaded by a trusted Knowledge adapter, never extracted from customer input.

    These are collection requirements, NOT adjudication/eligibility rules. The
    adapter must verify published membership and approval before constructing it.
    """

    tenant_id: UUID
    knowledge_version_id: UUID
    knowledge_digest: Digest
    document_id: UUID
    provenance: KnowledgeProvenance
    requirements: dict[IssueClass, tuple[RequiredField, ...]]

    @field_validator("requirements")
    @classmethod
    def complete_class_configuration(
        cls, value: dict[IssueClass, tuple[RequiredField, ...]]
    ) -> dict[IssueClass, tuple[RequiredField, ...]]:
        if set(value) != set(ISSUE_CLASSES):
            raise ValueError("policy must explicitly configure all issue classes")
        return {key: tuple(sorted(set(fields))) for key, fields in value.items()}


class ClaimOrderReference(InputModel):
    """Tenant/customer-scoped reference supplied by the Orders adapter.

    resource_id is canonical across purchase-reference/order-id aliases. A
    customer assertion alone cannot set order_verified or establish ownership.
    """

    tenant_id: UUID
    customer_ref: Identifier
    binding_id: UUID
    resource_id: Identifier
    order_id: Identifier | None = None
    purchase_reference: Identifier | None = None
    order_verified: bool


class ClaimCompleteness(InputModel):
    state: Literal["OPEN", "AWAITING_INFORMATION", "READY_FOR_REVIEW"]
    missing_fields: tuple[str, ...]
    review_flags: tuple[str, ...]


class ClaimContribution(InputModel):
    message_id: UUID
    patch_digest: Digest


class PreparedClaimIntake(InputModel):
    """Preparation is not a Cases receipt, persisted case or business approval."""

    tenant_id: UUID
    customer_ref: Identifier
    binding_id: UUID
    draft: ClaimDraft
    contributions: tuple[ClaimContribution, ...] = Field(max_length=1000)
    deduplication_key: Digest | None
    content_digest: Digest
    policy: ApprovedClaimPolicy | None
    order_reference: ClaimOrderReference | None
    completeness: ClaimCompleteness
    case_created: Literal[False] = False
    business_decision: Literal["NOT_MADE"] = "NOT_MADE"
