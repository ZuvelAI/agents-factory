from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import RowMapping


IdentityMethod = Literal[
    "WHATSAPP_RECOGNITION",
    "ADDITIONAL_VERIFICATION",
    "OTP",
    "EXTERNAL_AUTH",
]
ChallengeStatus = Literal["PENDING", "PASSED", "FAILED", "EXPIRED", "LOCKED"]
EvidenceResult = Literal["VERIFIED", "FAILED"]
EvidenceScope = Literal["SESSION", "ACTION"]


class IdentityLevel(IntEnum):
    LEVEL_0 = 0
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3


class FrozenIdentityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IdentityEvidence(FrozenIdentityModel):
    id: UUID
    tenant_id: UUID
    customer_ref: str
    method: IdentityMethod
    result: EvidenceResult
    achieved_level: IdentityLevel
    scope: EvidenceScope
    bound_action_ref: str | None
    evidence_ref_digest: str = Field(pattern=r"[0-9a-f]{64}")
    verified_at: datetime
    expires_at: datetime
    consumed_at: datetime | None

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls.model_validate(dict(row))


class IdentityChallenge(FrozenIdentityModel):
    id: UUID
    tenant_id: UUID
    customer_ref: str
    required_level: IdentityLevel
    method: IdentityMethod
    secret_digest: str | None = Field(default=None, pattern=r"[0-9a-f]{64}")
    status: ChallengeStatus
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1, le=10)
    bound_action_ref: str | None
    expires_at: datetime
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls.model_validate(dict(row))


class IdentityAssessment(FrozenIdentityModel):
    tenant_id: UUID
    customer_ref: str
    achieved_level: IdentityLevel
    evidence_ids: tuple[UUID, ...]
    assessed_at: datetime


class AuthorizationDecision(FrozenIdentityModel):
    tenant_id: UUID
    customer_ref: str
    resource_type: str = Field(min_length=1, max_length=120)
    resource_id: str = Field(min_length=1, max_length=300)
    action: str = Field(pattern=r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")
    allowed: bool
    reason_code: str = Field(min_length=1, max_length=120)


class ChallengeReceipt(FrozenIdentityModel):
    challenge_id: UUID
    method: IdentityMethod
    required_level: IdentityLevel
    expires_at: datetime
