from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents_factory.modules.whatsapp.router import TestMessageRequest as MessageRequest
from agents_factory.modules.whatsapp.test_templates import simple_approved_templates


def template():
    return {"id": "123", "name": "hello_world", "language": "en_US",
            "status": "APPROVED", "category": "UTILITY",
            "components": [{"type": "BODY", "text": "Hello world"}]}


def test_approved_simple_template_is_available():
    result = simple_approved_templates({"data": [template()]})
    assert len(result) == 1
    assert result[0].name == "hello_world"
    assert result[0].variable_names == ()


@pytest.mark.parametrize("components", [
    [{"type": "BODY", "text": "Hello {{1}}"}],
    [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Hello"}],
    [{"type": "BODY", "text": "Hello"}, {"type": "BUTTONS", "buttons": []}],
    [], None, [{"type": "BODY", "text": None}],
])
def test_unsupported_template_is_not_offered(components):
    item = deepcopy(template())
    item["components"] = components
    assert simple_approved_templates({"data": [item]}) == []


@pytest.mark.parametrize("status", ["PENDING", "REJECTED", "PAUSED", "DISABLED"])
def test_unapproved_template_is_not_offered(status):
    item = template()
    item["status"] = status
    assert simple_approved_templates({"data": [item]}) == []


@pytest.mark.parametrize("recipient", ["", "+573001234567", "123", "abc", "0" * 12])
def test_invalid_recipient_rejected(recipient):
    with pytest.raises(ValidationError):
        MessageRequest(recipient=recipient, template_name="hello_world",
                       language="en_US", idempotency_key=uuid4())
