from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.identity.models import (
    AuthorizationDecision,
    IdentityAssessment,
    IdentityLevel,
)
from agents_factory.modules.identity.service import IdentityService


TENANT_ID = UUID("10000000-0000-0000-0000-000000000114")


def identity() -> IdentityService:
    return IdentityService(
        context=TenantContext(
            tenant_id=TENANT_ID,
            actor_id=None,
            actor_type="system",
            correlation_id=uuid4(),
        ),
        store=object(),  # type: ignore[arg-type]
    )


def assessment() -> IdentityAssessment:
    return IdentityAssessment(
        tenant_id=TENANT_ID,
        customer_ref="recognized-whatsapp-customer",
        achieved_level=IdentityLevel.LEVEL_3,
        evidence_ids=(uuid4(),),
        assessed_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


def test_strong_identity_does_not_override_resource_authorization() -> None:
    denied = AuthorizationDecision(
        tenant_id=TENANT_ID,
        customer_ref=assessment().customer_ref,
        resource_type="order",
        resource_id="order-not-owned-by-customer",
        action="orders.get_status",
        allowed=False,
        reason_code="resource_not_authorized",
    )

    with pytest.raises(DomainError) as caught:
        identity().require_for_action(
            assessment=assessment(),
            required_level=IdentityLevel.LEVEL_1,
            authorization=denied,
            action="orders.get_status",
            resource_type="order",
            resource_id="order-not-owned-by-customer",
        )

    assert caught.value.code == "action_not_authorized"


def test_matching_identity_and_explicit_authorization_are_both_required() -> None:
    allowed = AuthorizationDecision(
        tenant_id=TENANT_ID,
        customer_ref=assessment().customer_ref,
        resource_type="order",
        resource_id="owned-order",
        action="orders.get_status",
        allowed=True,
        reason_code="customer_owns_order",
    )

    identity().require_for_action(
        assessment=assessment(),
        required_level=IdentityLevel.LEVEL_3,
        authorization=allowed,
        action="orders.get_status",
        resource_type="order",
        resource_id="owned-order",
    )

    with pytest.raises(DomainError):
        identity().require_for_action(
            assessment=assessment().model_copy(
                update={"achieved_level": IdentityLevel.LEVEL_1}
            ),
            required_level=IdentityLevel.LEVEL_2,
            authorization=allowed,
            action="orders.get_status",
            resource_type="order",
            resource_id="owned-order",
        )

    with pytest.raises(DomainError):
        identity().require_for_action(
            assessment=assessment(),
            required_level=IdentityLevel.LEVEL_1,
            authorization=allowed,
            action="orders.cancel",
            resource_type="order",
            resource_id="owned-order",
        )
