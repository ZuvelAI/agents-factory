import pytest
from pydantic import ValidationError

from agents_factory.modules.approvals.models import RequestedDecisionResult
from agents_factory.modules.approvals.result_schema import (
    DecisionReceipt,
    DecisionResult,
    RESULTS,
    reviewer_result,
)


def test_customer_result_is_a_closed_safe_contract_not_free_text_or_a_boolean():
    for reason, (status, explanation, actions) in RESULTS.items():
        result = DecisionResult.for_reason(reason)
        assert result.status == status and result.next_actions == actions
        assert result.customer_safe_explanation == explanation
        for patch in (
            {"customer_safe_explanation": "<script>alert('private')</script>"},
            {"next_actions": ["refund_money"]},
            {"reason_code": "private_provider_failure"},
        ):
            with pytest.raises(ValidationError):
                DecisionResult.model_validate({**result.model_dump(), **patch})
    proposal = RequestedDecisionResult(
        reason_code="order_already_shipped",
        explanation="Private email: owner@example.test; invented success; 123456",
        requested_next_actions=("refund_money",),
    )
    approved = reviewer_result(decision="APPROVE", proposal=proposal)
    rejected = reviewer_result(decision="REJECT", proposal=proposal)
    assert approved.status == "pending_execution"
    assert (
        rejected.reason_code == "reviewer_rejected"
    )  # claimed business reason is not yet revalidated
    assert "owner@" not in approved.model_dump_json() + rejected.model_dump_json()
    assert "123456" not in approved.model_dump_json() + rejected.model_dump_json()
    for value in (
        True,
        False,
        {"status": "succeeded"},
        {**approved.model_dump(), "status": "succeeded"},
    ):
        with pytest.raises(ValidationError):
            DecisionResult.model_validate(value)
    with pytest.raises(ValidationError):
        DecisionReceipt(status="CLOSED", result=approved)
