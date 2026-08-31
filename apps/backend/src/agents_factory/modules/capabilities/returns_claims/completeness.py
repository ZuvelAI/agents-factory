from agents_factory.modules.capabilities.returns_claims.classifier import classify_issue
from agents_factory.modules.capabilities.returns_claims.models import (
    ClaimCompleteness,
    ClaimDraft,
    RequiredField,
)


ITEM_ISSUES = frozenset({"wrong_product", "damaged_product", "incomplete_order"})
EVIDENCE_ISSUES = frozenset({"wrong_product", "damaged_product", "nonconformity"})


def assess_completeness(
    draft: ClaimDraft, *, policy_fields: tuple[RequiredField, ...] | None
) -> ClaimCompleteness:
    """Check collection only; READY_FOR_REVIEW never means accepted/eligible."""
    missing: set[str] = set()
    flags: set[str] = set()
    issue = classify_issue(draft.issue_type)
    if issue is None:
        missing.add("issue_type")
    if not draft.description:
        missing.add("description")
    if not draft.order_id and not draft.purchase_reference:
        missing.add("order_id_or_purchase_reference")
    if not draft.requested_resolution:
        missing.add("requested_resolution")
    if issue in ITEM_ISSUES and not draft.item_ids:
        missing.add("item_ids")
    if (
        issue in EVIDENCE_ISSUES
        and not draft.evidence_ids
        and not draft.evidence_unavailable_reason
    ):
        missing.add("evidence_ids_or_unavailable_reason")
    if draft.evidence_unavailable_reason and not draft.evidence_ids:
        flags.add("customer_reports_evidence_unavailable")
    if policy_fields is None:
        # The business must supply policy; do not ask a customer to approve it.
        flags.add("approved_policy_unavailable")
    else:
        for field in policy_fields:
            if not getattr(draft, field):
                missing.add(field)
        if "evidence_ids" in missing:
            missing.discard("evidence_ids_or_unavailable_reason")
    return ClaimCompleteness(
        state="AWAITING_INFORMATION"
        if missing
        else "OPEN"
        if policy_fields is None
        else "READY_FOR_REVIEW",
        missing_fields=tuple(sorted(missing)),
        review_flags=tuple(sorted(flags)),
    )


def merge_draft(previous: ClaimDraft, patch: ClaimDraft) -> ClaimDraft:
    """Merge a message without losing existing media or silently changing a case.

    Null/empty values mean no update, not deletion. Identity/resource corrections
    and evidence removal need an explicit backoffice operation, outside intake.
    """
    for field in ("issue_type", "order_id", "purchase_reference"):
        old, new = getattr(previous, field), getattr(patch, field)
        if old is not None and new is not None and old != new:
            raise ValueError("claim_resource_or_class_changed")
    values = previous.model_dump(mode="json")
    values.update(
        patch.model_dump(
            mode="json", exclude_none=True, exclude={"item_ids", "evidence_ids"}
        )
    )
    values["item_ids"] = sorted(set(previous.item_ids) | set(patch.item_ids))
    values["evidence_ids"] = sorted(
        str(value) for value in set(previous.evidence_ids) | set(patch.evidence_ids)
    )
    return ClaimDraft.model_validate(values)
