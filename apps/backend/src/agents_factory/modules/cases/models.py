from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from agents_factory.modules.cases.contracts import CaseStatus
from agents_factory.modules.integrations.google.base import InputModel


CasePriority = Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]
TargetStatus = Literal["ON_TRACK", "APPROACHING_TARGET", "OVERDUE"]


def default_targets() -> dict[CasePriority, int]:
    return {"LOW": 2880, "NORMAL": 1440, "HIGH": 240, "CRITICAL": 30}


class CasePolicy(InputModel):
    """Trusted tenant configuration; never supplied by an LLM/customer request."""

    close_after_hours: int = Field(default=72, ge=1, le=8760)
    target_minutes: dict[CasePriority, int] = Field(default_factory=default_targets)
    # Operational threshold, configurable; not a customer-facing SLA.
    approaching_fraction: float = Field(default=0.8, gt=0, lt=1)
    priority_by_issue: dict[str, CasePriority] = Field(default_factory=dict)

    @model_validator(mode="after")
    def complete_targets(self) -> Self:
        if set(self.target_minutes) != {"LOW", "NORMAL", "HIGH", "CRITICAL"} or any(
            not 1 <= value <= 525600 for value in self.target_minutes.values()
        ):
            raise ValueError("all four positive case targets are required")
        return self


class CustomerResponse(InputModel):
    operation_id: UUID
    issue_persists: bool
    reason: str = Field(min_length=1, max_length=1000)


class CaseSubmission(InputModel):
    tenant_id: UUID
    customer_ref: str = Field(min_length=1, max_length=300)
    capability: Literal["orders", "returns_claims"]
    issue_type: str = Field(min_length=1, max_length=80)
    binding_id: UUID
    resource_id: str = Field(min_length=1, max_length=500)
    deduplication_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    intake: dict[str, object]
    initial_status: Literal["OPEN", "AWAITING_INFORMATION", "READY_FOR_REVIEW"]
    evidence_ids: tuple[UUID, ...] = ()


class CaseRecord(InputModel):
    id: UUID
    tenant_id: UUID
    customer_ref: str
    capability: Literal["orders", "returns_claims"]
    issue_type: str
    binding_id: UUID
    resource_id: str
    deduplication_key: str
    content_digest: str
    intake: dict[str, object]
    revision: int = Field(ge=1)
    status: CaseStatus
    priority: CasePriority
    policy: CasePolicy
    target_status: TargetStatus = "ON_TRACK"
    approaching_at: AwareDatetime
    target_at: AwareDatetime
    resolved_at: AwareDatetime | None = None
    close_at: AwareDatetime | None = None
    customer_result: str | None = None
    result_recorded_by: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class CustomerCaseStatus(InputModel):
    case_id: UUID
    status: CaseStatus
    customer_result: str | None


class CaseTransition(InputModel):
    operation_id: UUID
    expected_revision: int = Field(ge=1)
    target: CaseStatus
    reason: str = Field(min_length=1, max_length=1000)
    approval_reference: str | None = Field(default=None, min_length=1, max_length=300)
    action_reference: UUID | None = None
    customer_result: str | None = Field(default=None, min_length=1, max_length=4000)


class CaseEvent(InputModel):
    id: UUID
    case_id: UUID
    revision: int
    event_type: str
    actor_id: UUID
    actor_type: str
    correlation_id: UUID
    reason: str
    from_status: CaseStatus | None
    to_status: CaseStatus
    action_reference: UUID | None
    approval_reference: str | None
    evidence_ids: tuple[UUID, ...]
    created_at: datetime
