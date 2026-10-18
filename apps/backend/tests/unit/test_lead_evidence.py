"""Proposals cannot supply authority or turn assistant text into customer interest."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents_factory.modules.leads.models import LeadProposal, validate_evidence
from agents_factory.modules.runtime.contracts import TurnMessage


def test_customer_quote_and_declared_values_are_grounded():
    message_id = uuid4()
    message = TurnMessage(
        message_id, "user", "Soy Ana de Nexo. Quiero un agente de ventas"
    )
    proposal = LeadProposal(
        operation="CAPTURE",
        evidence=[{"message_id": message_id, "quote": message.text}],
        declared_name="Ana",
        declared_company="Nexo",
        service_interest="Agente de ventas",
    )
    validate_evidence(proposal, (message,), message_id)
    with pytest.raises(ValueError, match="evidence"):
        validate_evidence(
            proposal.model_copy(update={"declared_company": "Inventada"}),
            (message,),
            message_id,
        )


@pytest.mark.parametrize("kind", ["assistant", "foreign", "fabricated", "old"])
def test_untrusted_or_stale_evidence_is_rejected(kind):
    current, other = uuid4(), uuid4()
    message = TurnMessage(
        current, "assistant" if kind == "assistant" else "user", "Quiero un agente"
    )
    evidence_id = other if kind in {"foreign", "old"} else current
    quote = "Otra frase" if kind == "fabricated" else "Quiero un agente"
    messages = (
        (TurnMessage(other, "user", "Quiero un agente"), message)
        if kind == "old"
        else (message,)
    )
    proposal = LeadProposal(
        operation="CAPTURE", evidence=[{"message_id": evidence_id, "quote": quote}]
    )
    with pytest.raises(ValueError, match="evidence"):
        validate_evidence(proposal, messages, current)


@pytest.mark.parametrize(
    "extra",
    [{"tenant_id": str(uuid4())}, {"phone_number": "+573000000001"}, {"status": "WON"}],
)
def test_model_cannot_supply_identity_or_authority(extra):
    with pytest.raises(ValidationError):
        LeadProposal.model_validate(
            {
                "operation": "CAPTURE",
                "evidence": [{"message_id": uuid4(), "quote": "Quiero un agente"}],
                **extra,
            }
        )


def test_suppression_does_not_smuggle_commercial_data():
    with pytest.raises(ValidationError):
        LeadProposal(
            operation="SUPPRESS",
            evidence=[{"message_id": uuid4(), "quote": "No guardes mis datos"}],
            declared_company="Nexo",
        )


@pytest.mark.parametrize("quote", ["", " " * 4, "x" * 501, "sk-proj-" + "x" * 40])
def test_empty_oversized_and_credential_evidence_is_rejected(quote):
    with pytest.raises(ValidationError):
        LeadProposal(
            operation="CAPTURE", evidence=[{"message_id": uuid4(), "quote": quote}]
        )


def test_limits_and_corrections_are_strict():
    evidence = {"message_id": uuid4(), "quote": "Quiero un agente"}
    for changes in (
        {"evidence": [evidence] * 6},
        {"corrected_fields": ["tenant_id"]},
        {"declared_name": "x" * 201},
        {"need_summary": "x" * 2001},
    ):
        with pytest.raises(ValidationError):
            LeadProposal.model_validate(
                {"operation": "CAPTURE", "evidence": [evidence], **changes}
            )
