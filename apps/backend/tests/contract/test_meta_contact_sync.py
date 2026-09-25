from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from agents_factory.modules.whatsapp.meta_provider import (
    InvalidWebhookPayload,
    MetaCloudApiProvider,
)


def contact_payload(action="add"):
    contact = {"phone_number": "573000000001"}
    if action == "add":
        contact.update(full_name="Cliente de prueba", first_name="Cliente")
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-contacts",
                "changes": [
                    {
                        "field": "smb_app_state_sync",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "phone-contacts"},
                            "state_sync": [
                                {
                                    "type": "contact",
                                    "contact": contact,
                                    "action": action,
                                    "metadata": {"timestamp": "1700255121"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize("action", ["add", "remove"])
def test_contact_sync_is_distinct_from_customer_messages(action):
    batch = MetaCloudApiProvider(app_secret=SecretStr("test-only")).parse_webhook(
        contact_payload(action)
    )
    assert batch.inbound_events == ()
    assert batch.mobile_echoes == ()
    assert len(batch.contact_changes) == 1
    contact = batch.contact_changes[0]
    assert (contact.waba_id, contact.phone_number_id, contact.customer_wa_id) == (
        "waba-contacts",
        "phone-contacts",
        "573000000001",
    )
    assert contact.action == action
    assert contact.full_name == ("Cliente de prueba" if action == "add" else None)
    assert contact.occurred_at == datetime.fromtimestamp(1700255121, UTC)


@pytest.mark.parametrize(
    "mutation", ["invalid_action", "missing_phone", "missing_timestamp"]
)
def test_contact_sync_rejects_unroutable_changes(mutation):
    payload = contact_payload()
    change = payload["entry"][0]["changes"][0]["value"]["state_sync"][0]
    if mutation == "invalid_action":
        change["action"] = "clear_all"
    elif mutation == "missing_phone":
        change["contact"].pop("phone_number")
    else:
        change["metadata"].pop("timestamp")
    with pytest.raises(InvalidWebhookPayload):
        MetaCloudApiProvider(app_secret=SecretStr("test-only")).parse_webhook(payload)
