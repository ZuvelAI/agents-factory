import pytest
from pydantic import ValidationError

from agents_factory.modules.capabilities.orders.manifest import DEFINITIONS, action_gate
from agents_factory.modules.capabilities.orders.models import INPUTS
from agents_factory.modules.capabilities.orders.service import customer_message
from agents_factory.modules.integrations.orders import READS, WRITES


def test_order_tool_inputs_risk_gate_and_truthful_localized_messages():
    for operation in READS:
        assert DEFINITIONS[operation].risk == "LOW"
        assert (
            action_gate(operation, identity_level=0, confirmed=False, approved=False)
            == "IDENTITY_REQUIRED"
        )
    for operation in WRITES:
        assert (
            action_gate(operation, identity_level=2, confirmed=False, approved=False)
            == "CONFIRMATION_REQUIRED"
        )
    assert (
        action_gate(WRITES[3], identity_level=2, confirmed=True, approved=False)
        == "APPROVAL_REQUIRED"
    )
    assert (
        action_gate(WRITES[3], identity_level=2, confirmed=True, approved=True)
        == "READY"
    )
    assert (
        action_gate(
            READS[1], identity_level=2, confirmed=True, approved=True, supported=False
        )
        == "UNAVAILABLE"
    )
    for injected in (
        {"customer": {"customer_id": "7"}},
        {"expected_version": "a" * 64},
        {"confirmed": True},
        {"approved": True},
    ):
        with pytest.raises(ValidationError):
            INPUTS[READS[1]].model_validate({"order_id": "42", **injected})
    assert "aún no está cancelado" in customer_message(
        state="SUCCEEDED", operation=WRITES[3], language="es"
    )
    assert "has not been cancelled" in customer_message(
        state="SUCCEEDED", operation=WRITES[3], language="en"
    )
    assert "no implica aceptación" in customer_message(
        state="SUCCEEDED", operation="orders.create_claim", language="es"
    )
    assert "will not be repeated automatically" in customer_message(
        state="UNCERTAIN", operation=WRITES[0], language="en"
    )
