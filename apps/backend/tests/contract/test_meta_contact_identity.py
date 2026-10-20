from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider


def payload():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/meta/inbound_text.json").read_text()
    )


def parse(body):
    return (
        MetaCloudApiProvider(app_secret=SecretStr("test-only"))
        .parse_webhook(body)
        .inbound_events
    )


def test_matches_sender_not_first_contact_and_keeps_phone_separate():
    body = payload()
    value = body["entry"][0]["changes"][0]["value"]
    value["contacts"].insert(
        0, {"wa_id": "573999999999", "profile": {"name": "Otra persona"}}
    )
    value["contacts"][1]["profile"]["username"] = "cliente.zuvel"
    identity = parse(body)[0].contact_identity
    assert identity.profile_name == "Cliente Prueba"
    assert identity.username == "cliente.zuvel"
    assert identity.phone_number == "+573000000001"


def test_bsuid_only_does_not_become_phone_number():
    body = payload()
    value = body["entry"][0]["changes"][0]["value"]
    del value["messages"][0]["from"]
    value["messages"][0]["from_user_id"] = "CO.123456789"
    value["contacts"] = [
        {
            "user_id": "CO.123456789",
            "profile": {"name": "Ana", "username": "ana.ventas"},
        }
    ]
    identity = parse(body)[0].contact_identity
    assert identity.profile_name == "Ana"
    assert identity.username == "ana.ventas"
    assert identity.phone_number is None


@pytest.mark.parametrize(
    "contacts", [[], [{"wa_id": "573111111111", "profile": {"name": "No corresponde"}}]]
)
def test_absent_or_unrelated_profile_does_not_steal_another_name(contacts):
    body = payload()
    body["entry"][0]["changes"][0]["value"]["contacts"] = contacts
    identity = parse(body)[0].contact_identity
    assert identity.profile_name is None
    assert identity.username is None
    assert identity.phone_number == "+573000000001"


def test_optional_bad_metadata_does_not_reject_valid_message():
    body = deepcopy(payload())
    body["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"] = {
        "name": {"bad": "value"},
        "username": " ",
    }
    identity = parse(body)[0].contact_identity
    assert identity.profile_name is None
    assert identity.username is None


def test_numeric_opaque_id_is_not_a_phone():
    body = payload()
    value = body["entry"][0]["changes"][0]["value"]
    del value["messages"][0]["from"]
    value["messages"][0]["from_user_id"] = "1234567890123"
    value["contacts"] = []
    assert parse(body)[0].contact_identity.phone_number is None


def test_conflicting_contact_identifiers_are_not_assigned_to_sender():
    body = payload()
    value = body["entry"][0]["changes"][0]["value"]
    value["messages"][0]["from_user_id"] = "CO.sender"
    value["contacts"] = [
        {
            "wa_id": "573999999999",
            "user_id": "CO.sender",
            "profile": {"name": "Contradictorio"},
        }
    ]
    assert parse(body)[0].contact_identity.profile_name is None


def test_same_digits_in_phone_and_user_id_namespaces_do_not_match():
    body = payload()
    value = body["entry"][0]["changes"][0]["value"]
    del value["messages"][0]["from"]
    value["messages"][0]["from_user_id"] = "1234567890123"
    value["contacts"] = [
        {"wa_id": "1234567890123", "profile": {"name": "Otra identidad"}}
    ]
    assert parse(body)[0].contact_identity.profile_name is None
