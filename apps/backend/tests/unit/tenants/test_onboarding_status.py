from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from agents_factory.modules.tenants.onboarding import (
    CLASSIFICATIONS,
    OnboardingFacts,
    OnboardingStatusEngine,
)


TENANT_ID = UUID("019c2000-0000-7000-8000-000000000101")


def _standard_facts() -> OnboardingFacts:
    return OnboardingFacts(
        tenant_id=TENANT_ID,
        company_complete=True,
        agent_instance_id=UUID("20000000-0000-4000-8000-000000000039"),
        agent_version_id=UUID("30000000-0000-4000-8000-000000000039"),
        agent_version_number=7,
        agent_state="TEST",
        capability_names=("orders", "returns_claims", "appointments"),
        integrations_required=True,
        connector_binding_count=4,
        healthy_connector_binding_count=4,
        knowledge_binding_valid=True,
        pending_knowledge_reviews=0,
        policy_configured=True,
        identity_policy_configured=True,
        handoff_enabled=False,
        required_approval_actions=("orders.request_cancellation",),
        configured_approval_actions=("orders.request_cancellation",),
        whatsapp_connected=True,
        whatsapp_healthy=True,
        has_tested_version=True,
    )


def test_onboarding_status_is_derived_resumable_and_fail_closed() -> None:
    engine = OnboardingStatusEngine()

    empty = engine.evaluate(
        OnboardingFacts(tenant_id=TENANT_ID, company_complete=False)
    )
    assert len(empty.steps) == 12
    assert empty.classifications == CLASSIFICATIONS
    assert empty.current_step_slug == "company"
    assert empty.steps[0].status == "READY"
    assert empty.steps[1].status == "BLOCKED"
    assert all(
        step.instructions
        and step.required_fields
        and step.validations
        and step.test_actions
        and step.documentation
        for step in empty.steps
    )
    assert empty.steps[10].status == "BLOCKED"
    assert empty.steps[11].status == "BLOCKED"

    ready = engine.evaluate(_standard_facts())
    assert ready == engine.evaluate(_standard_facts())
    assert [step.status for step in ready.steps[:10]] == ["COMPLETE"] * 10
    assert ready.complete_steps == 10
    assert ready.current_step_slug == "quality-gate"
    assert ready.steps[10].status == "READY"
    assert ready.steps[10].blockers[0].code == "production_quality_gate_required"
    assert ready.steps[11].status == "BLOCKED"

    approved = engine.evaluate(
        replace(_standard_facts(), agent_state="QUALITY_GATE", quality_gate_passed=True)
    )
    assert approved.steps[10].status == "COMPLETE"
    assert approved.steps[11].status == "READY"

    published = engine.evaluate(
        replace(_standard_facts(), agent_state="PRODUCTION", quality_gate_passed=True)
    )
    assert published.steps[10].status == "COMPLETE"
    assert published.steps[11].status == "COMPLETE"

    changed = engine.evaluate(
        replace(
            _standard_facts(),
            agent_version_number=8,
            agent_state="DRAFT",
        )
    )
    assert changed.steps[9].status == "STALE"
    assert changed.steps[9].blockers[0].code == "tested_candidate_stale"
    assert changed.steps[10].status == "BLOCKED"
    assert changed.steps[10].blockers[0].code == "test_required"
    assert changed.current_step_slug == "test"
