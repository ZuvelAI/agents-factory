from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents_factory.common.context import TenantContext
from agents_factory.modules.capabilities.returns_claims.classifier import classify_issue
from agents_factory.modules.capabilities.returns_claims.completeness import (
    assess_completeness,
    merge_draft,
)
from agents_factory.modules.capabilities.returns_claims.manifest import (
    DEFINITIONS,
    action_gate,
)
from agents_factory.modules.capabilities.returns_claims.models import (
    ISSUE_CLASSES,
    ApprovedClaimPolicy,
    ClaimDraft,
    ClaimOrderReference,
    ClaimsBinding,
)
from agents_factory.modules.capabilities.returns_claims.service import (
    ClaimIntakeRejected,
    ClaimsIntakeService,
)
from agents_factory.modules.identity.models import IdentityAssessment
from agents_factory.modules.knowledge.models import KnowledgeProvenance


def test_all_classes_policy_completeness_and_forbidden_authority():
    for issue in ISSUE_CLASSES:
        assert classify_issue(issue) == issue
        draft = ClaimDraft(
            issue_type=issue,
            order_id="42",
            description="Problema con la compra",
            item_ids=("item-1",),
            requested_resolution="Solicito revisión",
            evidence_unavailable_reason="No dispongo de fotos",
        )
        assessment = assess_completeness(draft, policy_fields=())
        assert assessment.state == "READY_FOR_REVIEW"
        assert "customer_reports_evidence_unavailable" in assessment.review_flags
        assert assess_completeness(draft, policy_fields=None).state == "OPEN"
        required = assess_completeness(
            draft, policy_fields=("evidence_ids", "incident_date", "purchase_date")
        )
        assert required.state == "AWAITING_INFORMATION"
        assert required.missing_fields == (
            "evidence_ids",
            "incident_date",
            "purchase_date",
        )
    assert classify_issue("refund_approved") is None
    assert (
        "issue_type"
        in assess_completeness(ClaimDraft(), policy_fields=()).missing_fields
    )
    damaged = ClaimDraft(
        issue_type="damaged_product",
        order_id="42",
        description="Roto",
        requested_resolution="Revisión",
    )
    assert assess_completeness(damaged, policy_fields=()).missing_fields == (
        "evidence_ids_or_unavailable_reason",
        "item_ids",
    )
    with pytest.raises(ValueError, match="claim_resource_or_class_changed"):
        merge_draft(damaged, ClaimDraft(order_id="43"))
    for field, value in (
        ("approved", True),
        ("confirmed", True),
        ("tenant_id", str(uuid4())),
        ("customer_ref", "someone-else"),
        ("order_verified", True),
        ("policy", {}),
        ("case_status", "RESOLVED"),
        ("refund_amount", 200),
    ):
        with pytest.raises(ValidationError):
            ClaimDraft.model_validate({field: value})
    with pytest.raises(ValidationError):
        ClaimDraft(description="   ")
    for operation in (
        "approve_return",
        "refund",
        "issue_credit_note",
        "promise_acceptance",
    ):
        name = "returns_claims." + operation
        assert name not in DEFINITIONS
        assert action_gate(name, identity_level=3, confirmed=True) == "UNAVAILABLE"
    assert (
        action_gate(
            "returns_claims.create_or_update_case", identity_level=1, confirmed=False
        )
        == "CONFIRMATION_REQUIRED"
    )
    assert (
        action_gate("returns_claims.get_case_status", identity_level=0, confirmed=True)
        == "IDENTITY_REQUIRED"
    )
    assert (
        action_gate(
            "returns_claims.create_or_update_case",
            identity_level=1,
            confirmed=True,
            supported=False,
        )
        == "UNAVAILABLE"
    )


async def test_incremental_intake_replay_provenance_and_scope_fail_closed():
    now = datetime.now(UTC)
    tenant_id, binding_id, evidence_a, evidence_b = (uuid4() for _ in range(4))
    context = TenantContext(tenant_id, uuid4(), "system", uuid4())
    binding = ClaimsBinding(
        tenant_id=tenant_id,
        binding_id=binding_id,
        knowledge_version_id=uuid4(),
        knowledge_digest="a" * 64,
    )
    policy = ApprovedClaimPolicy(
        tenant_id=tenant_id,
        knowledge_version_id=binding.knowledge_version_id,
        knowledge_digest=binding.knowledge_digest,
        document_id=uuid4(),
        provenance=KnowledgeProvenance(
            source_id=uuid4(),
            source_version_id=uuid4(),
            authority="AUTHORITATIVE",
            verified_at=now,
            approved_by_admin_id=uuid4(),
            content_digest="b" * 64,
        ),
        requirements={issue: ("incident_date",) for issue in ISSUE_CLASSES},
    )
    reference = ClaimOrderReference(
        tenant_id=tenant_id,
        customer_ref="customer-1",
        binding_id=binding_id,
        resource_id="order:42",
        order_id="42",
        order_verified=True,
    )
    identity = IdentityAssessment(
        tenant_id=tenant_id,
        customer_ref="customer-1",
        achieved_level=1,
        evidence_ids=(),
        assessed_at=now,
    )

    class PrivateEvidence:
        ids = {evidence_a, evidence_b}
        checks = []

        async def allowed(self, *, context, customer_ref, evidence_id):
            self.checks.append(evidence_id)
            return (
                context.tenant_id == tenant_id
                and customer_ref == "customer-1"
                and evidence_id in self.ids
            )

    media = PrivateEvidence()
    service = ClaimsIntakeService(evidence=media, now=lambda: now)

    async def prepare(draft, *, previous=None, message_id=None, **overrides):
        return await service.prepare(
            **{
                "context": context,
                "binding": binding,
                "customer_ref": "customer-1",
                "assessment": identity,
                "message_id": message_id or uuid4(),
                "draft": draft,
                "policy": policy,
                "order_reference": reference,
                "previous": previous,
                **overrides,
            }
        )

    first_message = uuid4()
    first_patch = ClaimDraft(
        issue_type="damaged_product", order_id="42", description="Caja rota"
    )
    first = await prepare(first_patch, message_id=first_message)
    assert first.completeness.state == "AWAITING_INFORMATION"
    assert first.deduplication_key is not None
    second = await prepare(
        ClaimDraft(
            item_ids=("item-1",),
            evidence_ids=(evidence_a,),
            incident_date=now.date(),
            requested_resolution="Solicito reembolso",
        ),
        previous=first,
    )
    assert second.completeness.state == "READY_FOR_REVIEW"
    third = await prepare(
        ClaimDraft(description="Corrección: producto roto", evidence_ids=(evidence_b,)),
        previous=second,
    )
    assert (
        third.deduplication_key == second.deduplication_key == first.deduplication_key
    )
    assert set(third.draft.evidence_ids) == {evidence_a, evidence_b}
    assert third.policy.provenance == policy.provenance
    assert not third.case_created and third.business_decision == "NOT_MADE"
    assert third.draft.requested_resolution == "Solicito reembolso"
    replay = await prepare(first_patch, previous=third, message_id=first_message)
    assert replay.content_digest == third.content_digest
    assert replay.contributions == third.contributions
    assert replay.draft.description == "Corrección: producto roto"
    repeated = await prepare(third.draft, previous=third)
    assert repeated.content_digest == third.content_digest
    assert len(repeated.contributions) == len(third.contributions) + 1
    assert all(evidence_id in media.checks for evidence_id in (evidence_a, evidence_b))

    for overrides, reason in (
        (
            {"context": TenantContext(tenant_id, uuid4(), "customer", uuid4())},
            "backend_actor_required",
        ),
        ({"customer_ref": "another-customer"}, "claim_identity_required"),
        (
            {
                "assessment": identity.model_copy(
                    update={"assessed_at": now - timedelta(minutes=6)}
                )
            },
            "claim_identity_required",
        ),
        (
            {
                "assessment": identity.model_copy(
                    update={"assessed_at": now.replace(tzinfo=None)}
                )
            },
            "claim_identity_required",
        ),
        (
            {"binding": binding.model_copy(update={"tenant_id": uuid4()})},
            "claim_binding_unavailable",
        ),
        (
            {"policy": policy.model_copy(update={"knowledge_digest": "c" * 64})},
            "claim_policy_mismatch",
        ),
        (
            {"policy": policy.model_copy(update={"tenant_id": uuid4()})},
            "claim_policy_mismatch",
        ),
        (
            {
                "order_reference": reference.model_copy(
                    update={"customer_ref": "another-customer"}
                )
            },
            "claim_order_reference_mismatch",
        ),
        (
            {"order_reference": reference.model_copy(update={"order_id": "43"})},
            "claim_order_reference_mismatch",
        ),
        (
            {
                "order_reference": reference.model_copy(
                    update={"resource_id": "other-order"}
                ),
                "previous": third,
            },
            "claim_deduplication_scope_changed",
        ),
        (
            {"previous": third.model_copy(update={"tenant_id": uuid4()})},
            "claim_previous_scope_mismatch",
        ),
        (
            {"previous": third, "message_id": first_message},
            "claim_message_replay_conflict",
        ),
    ):
        with pytest.raises(ClaimIntakeRejected, match=reason):
            await prepare(third.draft, **overrides)
    assert (await prepare(third.draft, policy=None)).completeness.state == "OPEN"
    assert (
        await prepare(third.draft, order_reference=None)
    ).completeness.state == "OPEN"
    reported = await prepare(
        third.draft,
        order_reference=reference.model_copy(update={"order_verified": False}),
    )
    assert (
        "reported_purchase_requires_backoffice_verification"
        in reported.completeness.review_flags
    )
    media.ids.remove(evidence_a)
    with pytest.raises(ClaimIntakeRejected, match="claim_evidence_unavailable"):
        await prepare(first_patch, previous=third, message_id=first_message)
    with pytest.raises(ClaimIntakeRejected, match="claim_evidence_unavailable"):
        await ClaimsIntakeService(now=lambda: now).prepare(
            context=context,
            binding=binding,
            customer_ref="customer-1",
            assessment=identity,
            message_id=uuid4(),
            draft=third.draft,
            policy=policy,
            order_reference=reference,
        )
