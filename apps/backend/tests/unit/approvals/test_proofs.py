from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents_factory.modules.approvals.models import ApprovalError, ApprovalRouteDraft
from agents_factory.modules.approvals.otp import issue_otp, verify_otp
from agents_factory.modules.approvals.routes import (
    validate_required_routes,
    validate_route_action,
)
from agents_factory.modules.approvals.tokens import ApprovalProofs, LinkClaims
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY
from agents_factory.modules.secrets.redaction import ResolvedSecret
from apps.backend.tests.approval_support import ACTION, EMAILS
from scheduler.approval_jobs import configure_approval_jobs


def test_approval_proofs_route_gate_and_safe_defaults():
    proofs = ApprovalProofs(ResolvedSecret(b"unit-approval-material-32-bytes!!!"))
    claims = LinkClaims(uuid4(), uuid4(), uuid4(), datetime(2026, 9, 1, tzinfo=UTC))
    wrapped = proofs.issue_link(claims)
    link_value = wrapped.reveal().decode()
    assert proofs.verify_link(link_value) == claims and link_value not in repr(wrapped)
    altered = proofs.issue_link(replace(claims, tenant_id=uuid4())).reveal().decode()
    with pytest.raises(ApprovalError):
        proofs.verify_link(
            altered.rsplit(".", 1)[0] + "." + link_value.rsplit(".", 1)[1]
        )
    for bad in ("", link_value + "x", link_value.upper()):
        with pytest.raises(ApprovalError):
            proofs.verify_link(bad)
    challenge = uuid4()
    otp = issue_otp(proofs, challenge)
    code = otp.plaintext.reveal().decode()
    assert code not in repr(otp) and code != otp.digest
    assert verify_otp(proofs, challenge, code, otp.digest)
    assert not verify_otp(proofs, uuid4(), code, otp.digest)
    assert not verify_otp(proofs, challenge, code + " ", otp.digest)
    route = ApprovalRouteDraft(
        ref="review", capability="orders", action=ACTION, authorized_emails=EMAILS
    )
    definitions = [
        a for m in V1_CAPABILITY_REGISTRY.list() for a in m.actions if a.name == ACTION
    ]
    assert definitions and definitions[0].risk == "HIGH"
    with pytest.raises(ApprovalError):
        validate_required_routes(definitions, {})
    validate_required_routes(definitions, {ACTION: route})
    with pytest.raises(ApprovalError):
        validate_route_action(route.model_copy(update={"action": "orders.nonexistent"}))
    with pytest.raises(ValidationError):
        ApprovalRouteDraft.model_validate(
            {**route.model_dump(), "authorized_emails": [EMAILS[0], EMAILS[0].upper()]}
        )
    metadata = proofs.audit_metadata(
        tenant_id=claims.tenant_id,
        at=claims.expires_at,
        ip="192.0.2.77",
        user_agent="Private browser",
    )
    assert "192.0.2" not in str(metadata) and "Private browser" not in str(metadata)
    assert configure_approval_jobs({"job_handlers": {}}) == {}
