from agents_factory.modules.evals.models import QualityGateRunRequest
from agents_factory.modules.evals.runner import REQUIRED_PRODUCTION_SUITES


def test_default_quality_gate_suite_is_complete_and_exact_versioned() -> None:
    request = QualityGateRunRequest(
        agent_spec_digest="a" * 64,
        knowledge_digest="b" * 64,
        code_digest="c" * 64,
    )

    assert set(request.suites) == REQUIRED_PRODUCTION_SUITES
    assert (
        len(
            {
                request.agent_spec_digest,
                request.knowledge_digest,
                request.code_digest,
            }
        )
        == 3
    )


def test_every_critical_blocker_has_a_stable_contract_value() -> None:
    request = QualityGateRunRequest(
        agent_spec_digest="a" * 64,
        knowledge_digest="b" * 64,
        code_digest="c" * 64,
        hard_blockers=(
            "CROSS_TENANT_ACCESS",
            "SENSITIVE_ACTION_WITHOUT_AUTHORIZATION",
            "CONFIRMATION_BYPASS",
            "HIGH_APPROVAL_BYPASS",
            "SECRET_EXPOSURE",
            "AI_REPLY_DURING_HUMAN_ACTIVE",
            "FALSE_SUCCESS_AFTER_UNCERTAIN_WRITE",
        ),
    )

    assert len(request.hard_blockers) == 7
