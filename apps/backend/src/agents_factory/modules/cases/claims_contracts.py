from __future__ import annotations

from typing import Protocol, Self
from uuid import UUID

from pydantic import Field, model_validator

from agents_factory.common.context import TenantContext
from agents_factory.modules.cases.contracts import CaseStatus, CasesUnavailable
from agents_factory.modules.capabilities.returns_claims.models import (
    PreparedClaimIntake,
)
from agents_factory.modules.integrations.google.base import InputModel


class ClaimCase(InputModel):
    case_id: UUID
    intake: PreparedClaimIntake
    revision: int = Field(ge=1)
    status: CaseStatus
    customer_result: str | None = Field(default=None, min_length=1, max_length=4000)
    result_recorded_by: UUID | None = None

    @model_validator(mode="after")
    def recorded_result(self) -> Self:
        if self.intake.deduplication_key is None:
            raise ValueError("case requires a scoped deduplication key")
        if self.customer_result is not None and self.result_recorded_by is None:
            raise ValueError("customer result requires a verified backoffice actor")
        return self


class ClaimCaseConflict(ValueError):
    pass


class ClaimCasesPort(Protocol):
    """Task 30 persistence boundary, not an in-memory production implementation.

    All calls enforce tenant AND customer scope. find_open uses the approved
    equivalent-open-case policy. upsert commits independently of the outer Action:
    atomically dedupe, CAS revision, append provenance and store the idempotent
    receipt keyed by tenant/action/digest. Replay MUST precede revision validation.
    A matching repeated semantic intake reuses the case/revision, not a new case.
    Intake may only set OPEN/AWAITING_INFORMATION/READY_FOR_REVIEW, never overwrite
    a later backoffice state/result. Concurrent or changed cases require rereview.
    """

    @property
    def available(self) -> bool: ...

    async def find_open(
        self, *, context: TenantContext, customer_ref: str, deduplication_key: str
    ) -> ClaimCase | None: ...

    async def get(
        self, *, context: TenantContext, customer_ref: str, case_id: UUID
    ) -> ClaimCase | None: ...

    async def upsert(
        self,
        *,
        context: TenantContext,
        action_id: UUID,
        parameter_digest: str,
        intake: PreparedClaimIntake,
        expected_revision: int,
        case_id: UUID | None,
    ) -> ClaimCase: ...


class UnavailableClaimCases:
    available = False

    async def find_open(
        self, *, context: TenantContext, customer_ref: str, deduplication_key: str
    ) -> ClaimCase | None:
        raise CasesUnavailable("claim_cases_unavailable")

    async def get(
        self, *, context: TenantContext, customer_ref: str, case_id: UUID
    ) -> ClaimCase | None:
        raise CasesUnavailable("claim_cases_unavailable")

    async def upsert(
        self,
        *,
        context: TenantContext,
        action_id: UUID,
        parameter_digest: str,
        intake: PreparedClaimIntake,
        expected_revision: int,
        case_id: UUID | None,
    ) -> ClaimCase:
        raise CasesUnavailable("claim_cases_unavailable")
