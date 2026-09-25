import pytest
from pydantic import SecretStr

from agents_factory.modules.whatsapp.meta_provider import (
    InvalidWebhookPayload,
    MetaCloudApiProvider,
)


def payload():
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-history",
                "changes": [
                    {
                        "field": "history",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "phone-history"},
                            "history": [
                                {
                                    "metadata": {
                                        "phase": 0,
                                        "chunk_order": 1,
                                        "progress": 55,
                                    },
                                    "threads": [
                                        {
                                            "id": "573000000001",
                                            "messages": [
                                                {
                                                    "from": "573000000001",
                                                    "id": "old-1",
                                                    "timestamp": "1739230970",
                                                    "type": "text",
                                                    "text": {
                                                        "body": "Pregunta antigua"
                                                    },
                                                    "history_context": {
                                                        "status": "READ"
                                                    },
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def parse(data):
    return MetaCloudApiProvider(app_secret=SecretStr("test-only")).parse_webhook(data)


def test_history_preserves_chunk_and_message_without_live_input():
    batch = parse(payload())
    assert batch.inbound_events == batch.mobile_echoes == batch.delivery_statuses == ()
    assert len(batch.history_sync) == 1
    event = batch.history_sync[0]
    assert (event.waba_id, event.phone_number_id) == ("waba-history", "phone-history")
    assert event.chunks[0]["metadata"] == {"phase": 0, "chunk_order": 1, "progress": 55}
    assert event.chunks[0]["threads"][0]["messages"][0]["text"] == {
        "body": "Pregunta antigua"
    }


def test_history_media_placeholder_is_not_a_live_message():
    data = payload()
    message = data["entry"][0]["changes"][0]["value"]["history"][0]["threads"][0][
        "messages"
    ][0]
    message.pop("text")
    message["type"] = "media_placeholder"
    batch = parse(data)
    assert batch.inbound_events == ()
    assert (
        batch.history_sync[0].chunks[0]["threads"][0]["messages"][0]["type"]
        == "media_placeholder"
    )


def test_declined_history_is_preserved_as_sync_error():
    data = payload()
    data["entry"][0]["changes"][0]["value"]["history"] = [
        {"errors": [{"code": 2593109}]}
    ]
    batch = parse(data)
    assert batch.history_sync[0].chunks == ({"errors": [{"code": 2593109}]},)
    assert batch.inbound_events == ()


@pytest.mark.parametrize(
    "field,value", [("progress", 101), ("phase", -1), ("chunk_order", -1)]
)
def test_invalid_history_progress_is_rejected(field, value):
    data = payload()
    data["entry"][0]["changes"][0]["value"]["history"][0]["metadata"][field] = value
    with pytest.raises(InvalidWebhookPayload):
        parse(data)


def test_delayed_history_media_is_not_routed_to_live_input():
    data = payload()
    value = data["entry"][0]["changes"][0]["value"]
    value.pop("history")
    value["messages"] = [
        {
            "from": "573000000001",
            "id": "old-media",
            "timestamp": "1739230970",
            "type": "image",
            "image": {"id": "media-1"},
        }
    ]
    batch = parse(data)
    assert batch.inbound_events == ()
    assert batch.history_sync[0].media_messages[0]["image"] == {"id": "media-1"}
