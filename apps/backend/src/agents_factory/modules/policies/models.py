from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agents_factory.modules.identity.models import IdentityLevel


RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class FrozenPolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActionRequirement(FrozenPolicyModel):
    identity_level: IdentityLevel
    confirmation_required: bool
    approval_required: bool


class TenantActionPolicy(FrozenPolicyModel):
    identity_level: IdentityLevel | None = None
    confirmation_required: bool | None = None
    approval_required: bool | None = None
