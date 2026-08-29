from __future__ import annotations

from agents_factory.modules.identity.models import IdentityLevel
from agents_factory.modules.policies.models import (
    ActionRequirement,
    RiskLevel,
    TenantActionPolicy,
)


class WeakenedSafetyPolicy(ValueError):
    pass


class ActionPolicyEvaluator:
    def evaluate(
        self,
        *,
        risk: RiskLevel,
        minimum_identity_level: IdentityLevel,
        tenant_policy: TenantActionPolicy | None = None,
    ) -> ActionRequirement:
        minimum = ActionRequirement(
            identity_level=minimum_identity_level,
            confirmation_required=risk in {"MEDIUM", "HIGH"},
            approval_required=risk == "HIGH",
        )
        if tenant_policy is None:
            return minimum
        resolved = ActionRequirement(
            identity_level=(
                minimum.identity_level
                if tenant_policy.identity_level is None
                else tenant_policy.identity_level
            ),
            confirmation_required=(
                minimum.confirmation_required
                if tenant_policy.confirmation_required is None
                else tenant_policy.confirmation_required
            ),
            approval_required=(
                minimum.approval_required
                if tenant_policy.approval_required is None
                else tenant_policy.approval_required
            ),
        )
        if (
            resolved.identity_level < minimum.identity_level
            or minimum.confirmation_required
            and not resolved.confirmation_required
            or minimum.approval_required
            and not resolved.approval_required
        ):
            raise WeakenedSafetyPolicy("tenant policy cannot weaken platform minimums")
        return resolved
