from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from agents_factory.modules.whatsapp.meta_provider import (
    InvalidWebhookPayload,
    MetaCloudApiProvider,
)


def echo_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "smb_message_echoes",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "phone_number_id": "phone-1",
                                "display_phone_number": "573000000099",
                            },
                            "message_echoes": [
                                {
                                    "id": "wamid.mobile-1",
                                    "from": "573000000099",
                                    "to": "573000000001",
                                    "timestamp": "1700255121",
                                    "type": "text",
                                    "text": {"body": "Te atiendo personalmente"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def test_mobile_echo_is_not_customer_input() -> None:
    provider = MetaCloudApiProvider(app_secret=SecretStr("test-only"))
    batch = provider.parse_webhook(echo_payload())
    assert batch.inbound_events == ()
    assert batch.delivery_statuses == ()
    assert len(batch.mobile_echoes) == 1
    echo = batch.mobile_echoes[0]
    assert echo.phone_number_id == "phone-1"
    assert echo.waba_id == "waba-1"
    assert echo.recipient_wa_id == "573000000001"
    assert echo.whatsapp_message_id == "wamid.mobile-1"
    assert echo.content == {"text": "Te atiendo personalmente"}
    assert echo.occurred_at == datetime.fromtimestamp(1700255121, UTC)


@pytest.mark.parametrize("field", ["to", "id", "timestamp"])
def test_mobile_echo_requires_routing_and_deduplication_fields(field: str) -> None:
    payload = deepcopy(echo_payload())
    del payload["entry"][0]["changes"][0]["value"]["message_echoes"][0][field]
    with pytest.raises(InvalidWebhookPayload):
        MetaCloudApiProvider(app_secret=SecretStr("test-only")).parse_webhook(payload)
