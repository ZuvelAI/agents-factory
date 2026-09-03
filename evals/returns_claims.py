from agents_factory.modules.capabilities.returns_claims.classifier import classify_issue
from agents_factory.modules.capabilities.returns_claims.completeness import (
    assess_completeness,
)
from agents_factory.modules.capabilities.returns_claims.manifest import action_gate
from agents_factory.modules.capabilities.returns_claims.models import ClaimDraft
from evals.case_schema import ClaimIntakeBehavior, ClaimIntakeProbe


def observe_claim_intake(probe: ClaimIntakeProbe) -> ClaimIntakeBehavior:
    """Exercise real intake functions, not fake-runtime response wording.

    This deliberately does NOT claim case persistence, runtime wiring or real
    model classification/quality; those require the later integration evidence.
    """
    gate = action_gate(
        probe.operation,
        identity_level=probe.identity_level,
        confirmed=probe.confirmed,
        supported=probe.supported,
    )
    if gate != "READY" or probe.draft is None:
        return ClaimIntakeBehavior.model_validate({"state": gate})
    draft = ClaimDraft.model_validate(probe.draft)
    completeness = assess_completeness(draft, policy_fields=probe.policy_fields)
    return ClaimIntakeBehavior(
        state=completeness.state,
        issue_type=classify_issue(draft.issue_type),
        missing_fields=completeness.missing_fields,
    )
