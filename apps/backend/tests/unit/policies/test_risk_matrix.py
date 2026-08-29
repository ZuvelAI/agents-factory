from __future__ import annotations

import pytest

from agents_factory.modules.identity.models import IdentityLevel
from agents_factory.modules.policies.evaluator import (
    ActionPolicyEvaluator,
    WeakenedSafetyPolicy,
)
from agents_factory.modules.policies.models import TenantActionPolicy


@pytest.mark.parametrize(
    ("risk", "confirmation", "approval"),
    (("LOW", False, False), ("MEDIUM", True, False), ("HIGH", True, True)),
)
def test_platform_minimum_risk_matrix(
    risk: str, confirmation: bool, approval: bool
) -> None:
    requirement = ActionPolicyEvaluator().evaluate(
        risk=risk,  # type: ignore[arg-type]
        minimum_identity_level=IdentityLevel.LEVEL_1,
    )

    assert requirement.confirmation_required is confirmation
    assert requirement.approval_required is approval


def test_tenant_policy_may_be_stricter_but_never_weaker() -> None:
    evaluator = ActionPolicyEvaluator()
    stricter = evaluator.evaluate(
        risk="LOW",
        minimum_identity_level=IdentityLevel.LEVEL_1,
        tenant_policy=TenantActionPolicy(
            identity_level=IdentityLevel.LEVEL_2,
            confirmation_required=True,
            approval_required=True,
        ),
    )

    assert stricter.identity_level == IdentityLevel.LEVEL_2
    assert stricter.confirmation_required is True
    assert stricter.approval_required is True

    with pytest.raises(WeakenedSafetyPolicy):
        evaluator.evaluate(
            risk="HIGH",
            minimum_identity_level=IdentityLevel.LEVEL_2,
            tenant_policy=TenantActionPolicy(
                identity_level=IdentityLevel.LEVEL_1,
                confirmation_required=False,
                approval_required=False,
            ),
        )
