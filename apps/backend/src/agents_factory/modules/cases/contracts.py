from __future__ import annotations

from datetime import date
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from agents_factory.common.context import TenantContext
from agents_factory.modules.integrations.google.base import InputModel

IssueType = Literal[
    "missing_order",
    "wrong_product",
    "damaged_product",
    "delivery_delay",
    "create_claim",
]
CaseStatus = Literal[
    "OPEN",
    "AWAITING_INFORMATION",
    "READY_FOR_REVIEW",
    "PENDING_APPROVAL",
    "IN_PROGRESS",
    "RESOLVED",
    "CLOSED",
    "REOPENED",
    "REJECTED",
    "CANCELLED",
    "EXPIRED",
    "DUPLICATE",
]


class CaseIntake(InputModel):
    tenant_id: UUID
    customer_ref: str
    conversation_id: UUID
    capability: Literal["orders"] = "orders"
    issue_type: IssueType
    binding_id: UUID
    resource_id: str
    order_verified: bool
    description: str = Field(min_length=1, max_length=4000)
    item_ids: tuple[str, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    incident_date: date | None = None
    requested_resolution: str | None = None
    idempotency_key: UUID
    deduplication_key: str


class CaseReceipt(InputModel):
    case_id: UUID
    tenant_id: UUID
    customer_ref: str
    deduplication_key: str
    status: CaseStatus
    reused: bool = False


class CasesPort(Protocol):
    @property
    def available(self) -> bool: ...

    async def create_or_update(
        self, *, context: TenantContext, intake: CaseIntake
    ) -> CaseReceipt:
        """Task 30 must enforce tenant scope, idempotency and equivalent-open-case deduplication."""
        ...


class CasesUnavailable(RuntimeError):
    pass


class UnavailableCases:
    available = False

    async def create_or_update(
        self, *, context: TenantContext, intake: CaseIntake
    ) -> CaseReceipt:
        raise CasesUnavailable("case_creation_unavailable")
