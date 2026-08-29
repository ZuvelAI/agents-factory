from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import RowMapping

from agents_factory.modules.identity.models import IdentityLevel
from agents_factory.modules.policies.models import RiskLevel


ActionState = Literal[
    "REQUESTED",
    "IDENTITY_VERIFIED",
    "AWAITING_CONFIRMATION",
    "CONFIRMED",
    "AWAITING_APPROVAL",
    "EXECUTING",
    "SUCCEEDED",
    "REJECTED",
    "FAILED",
    "UNCERTAIN",
    "EXPIRED",
    "HANDED_OFF",
]
TerminalActionState = Literal[
    "SUCCEEDED", "REJECTED", "FAILED", "UNCERTAIN", "EXPIRED", "HANDED_OFF"
]


class FrozenActionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NormalizedParameters(FrozenActionModel):
    value: dict[str, object]
    canonical_json: str
    digest: str = Field(pattern=r"[0-9a-f]{64}")

    @classmethod
    def from_value(cls, value: dict[str, object]) -> Self:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return cls(
            value=json.loads(canonical),
            canonical_json=canonical,
            digest=hashlib.sha256(canonical.encode()).hexdigest(),
        )


class ActionRecord(FrozenActionModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    customer_ref: str
    capability: str
    action_type: str
    risk: RiskLevel
    required_identity_level: IdentityLevel
    achieved_identity_level: IdentityLevel
    parameters: dict[str, object]
    parameter_digest: str = Field(pattern=r"[0-9a-f]{64}")
    confirmation_required: bool
    confirmation_digest: str | None
    confirmed_at: datetime | None
    confirmation_expires_at: datetime | None
    approval_required: bool
    approval_route_ref: str | None
    approval_reference: str | None
    approved_at: datetime | None
    connector_binding_id: UUID
    connector_name: str
    state: ActionState
    result: dict[str, object]
    execution_attempts: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls.model_validate(dict(row))


class ActionOutcome(FrozenActionModel):
    action_id: UUID
    state: ActionState
    customer_message: str
    result: dict[str, object]


class PreconditionDecision(FrozenActionModel):
    valid: bool
    reason_code: str = Field(min_length=1, max_length=120)
