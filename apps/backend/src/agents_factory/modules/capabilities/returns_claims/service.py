from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.capabilities.orders.issues import (
    DenyEvidence,
    EvidenceAccess,
)
from agents_factory.modules.capabilities.returns_claims.completeness import (
    assess_completeness,
    merge_draft,
)
from agents_factory.modules.capabilities.returns_claims.models import (
    ApprovedClaimPolicy,
    ClaimContribution,
    ClaimDraft,
    ClaimOrderReference,
    ClaimsBinding,
    PreparedClaimIntake,
)
from agents_factory.modules.identity.models import IdentityAssessment


class ClaimIntakeRejected(ValueError):
    """Code-owned error codes only; never customer data or provider diagnostics."""


class ClaimsIntakeService:
    """Prepare a conservative handoff. No writes, tools or case receipts here.

    Callers supply trusted identity, pinned Knowledge and scoped Orders results.
    Task 30's Cases adapter must serialize concurrent updates and preserve action
    idempotency. Runtime/Google execution must use confirmed Actions, not call this
    preparation method as a substitute for authorization or persistence.
    """

    def __init__(
        self,
        *,
        evidence: EvidenceAccess | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.evidence = evidence or DenyEvidence()
        self.now = now or (lambda: datetime.now(UTC))

    async def prepare(
        self,
        *,
        context: TenantContext,
        binding: ClaimsBinding,
        customer_ref: str,
        assessment: IdentityAssessment,
        message_id: UUID,
        draft: ClaimDraft,
        policy: ApprovedClaimPolicy | None = None,
        order_reference: ClaimOrderReference | None = None,
        previous: PreparedClaimIntake | None = None,
    ) -> PreparedClaimIntake:
        if (
            context.actor_type not in {"system", "platform_admin"}
            or context.actor_id is None
        ):
            raise ClaimIntakeRejected("backend_actor_required")
        if context.tenant_id != binding.tenant_id:
            raise ClaimIntakeRejected("claim_binding_unavailable")
        if (
            assessment.tenant_id != context.tenant_id
            or assessment.customer_ref != customer_ref
            or assessment.achieved_level < 1
            or assessment.assessed_at.tzinfo is None
            or not timedelta(seconds=-30)
            <= self.now() - assessment.assessed_at
            <= timedelta(minutes=5)
        ):
            raise ClaimIntakeRejected("claim_identity_required")
        contributions = previous.contributions if previous is not None else ()
        patch_digest = NormalizedParameters.from_value(
            draft.model_dump(mode="json")
        ).digest
        if previous is not None:
            if (previous.tenant_id, previous.binding_id, previous.customer_ref) != (
                context.tenant_id,
                binding.binding_id,
                customer_ref,
            ):
                raise ClaimIntakeRejected("claim_previous_scope_mismatch")
            old = next(
                (part for part in contributions if part.message_id == message_id), None
            )
            if old is not None:
                if old.patch_digest != patch_digest:
                    raise ClaimIntakeRejected("claim_message_replay_conflict")
                # An old delivery must not overwrite a newer customer correction.
                draft = previous.draft
            else:
                try:
                    draft = merge_draft(previous.draft, draft)
                except ValueError as error:
                    raise ClaimIntakeRejected("claim_merge_rejected") from error
        if not any(part.message_id == message_id for part in contributions):
            contributions = (
                *contributions,
                ClaimContribution(message_id=message_id, patch_digest=patch_digest),
            )
        if len(contributions) > 1000:
            raise ClaimIntakeRejected("claim_intake_limit_requires_review")
        if policy is not None and (
            (policy.tenant_id, policy.knowledge_version_id, policy.knowledge_digest)
            != (
                binding.tenant_id,
                binding.knowledge_version_id,
                binding.knowledge_digest,
            )
            or policy.provenance.authority != "AUTHORITATIVE"
            or policy.provenance.verified_at.tzinfo is None
            or policy.provenance.verified_at > self.now() + timedelta(seconds=30)
        ):
            raise ClaimIntakeRejected("claim_policy_mismatch")
        if order_reference is not None and (
            (
                order_reference.tenant_id,
                order_reference.binding_id,
                order_reference.customer_ref,
            )
            != (context.tenant_id, binding.binding_id, customer_ref)
            or (
                draft.order_id is not None
                and draft.order_id != order_reference.order_id
            )
            or (
                draft.purchase_reference is not None
                and draft.purchase_reference != order_reference.purchase_reference
            )
            or (draft.order_id is None and draft.purchase_reference is None)
        ):
            raise ClaimIntakeRejected("claim_order_reference_mismatch")
        for evidence_id in draft.evidence_ids:
            # Revalidate ALL retained evidence, including on replay after deletion.
            if not await self.evidence.allowed(
                context=context, customer_ref=customer_ref, evidence_id=evidence_id
            ):
                raise ClaimIntakeRejected("claim_evidence_unavailable")
        completeness = assess_completeness(
            draft,
            policy_fields=policy.requirements[draft.issue_type]
            if policy is not None and draft.issue_type is not None
            else None,
        )
        flags = set(completeness.review_flags)
        if order_reference is None:
            flags.add("scoped_order_reference_unavailable")
        elif not order_reference.order_verified:
            flags.add("reported_purchase_requires_backoffice_verification")
        key = None
        if draft.issue_type is not None and order_reference is not None:
            key = NormalizedParameters.from_value(
                {
                    "tenant_id": str(context.tenant_id),
                    "customer_ref": customer_ref,
                    "capability": "returns_claims",
                    "issue_type": draft.issue_type,
                    "binding_id": str(binding.binding_id),
                    "resource_id": order_reference.resource_id,
                }
            ).digest
        if (
            previous is not None
            and previous.deduplication_key is not None
            and key is not None
            and key != previous.deduplication_key
        ):
            raise ClaimIntakeRejected("claim_deduplication_scope_changed")
        completeness = completeness.model_copy(
            update={
                "state": "OPEN"
                if completeness.state == "READY_FOR_REVIEW" and key is None
                else completeness.state,
                "review_flags": tuple(sorted(flags)),
            }
        )
        content_digest = NormalizedParameters.from_value(
            {
                "draft": draft.model_dump(mode="json"),
                "deduplication_key": key,
                "policy": policy.model_dump(mode="json")
                if policy is not None
                else None,
                "order_reference": order_reference.model_dump(mode="json")
                if order_reference is not None
                else None,
                "completeness": completeness.model_dump(mode="json"),
            }
        ).digest
        return PreparedClaimIntake(
            tenant_id=context.tenant_id,
            customer_ref=customer_ref,
            binding_id=binding.binding_id,
            draft=draft,
            contributions=contributions,
            deduplication_key=key,
            content_digest=content_digest,
            policy=policy,
            order_reference=order_reference,
            completeness=completeness,
        )
