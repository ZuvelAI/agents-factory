from copy import deepcopy

import pytest

from agents_factory.modules.whatsapp import history_sync


def history_payload():
    return {
        "chunks": [
            {
                "metadata": {"phase": 0, "chunk_order": 1, "progress": 55},
                "threads": [
                    {
                        "id": "customer",
                        "messages": [
                            {
                                "id": "out",
                                "from": "business",
                                "timestamp": "1739230955",
                                "type": "text",
                                "text": {"body": "Old answer"},
                            },
                            {
                                "id": "in",
                                "from": "customer",
                                "timestamp": "1739230970",
                                "type": "text",
                                "text": {"body": "Old question"},
                            },
                        ],
                    }
                ],
            }
        ],
        "media_messages": [],
    }


def test_history_projection_preserves_customer_and_business_messages():
    result = history_sync.project_history(history_payload())
    assert [
        (m.provider_id, m.customer_wa_id, m.direction) for m in result.messages
    ] == [("out", "customer", "outbound"), ("in", "customer", "inbound")]
    assert result.messages[0].content["text"] == {"body": "Old answer"}
    assert result.messages[1].occurred_at.isoformat() == "2025-02-10T23:42:50+00:00"
    assert result.progress == ((0, 1, 55),)
    assert result.errors == ()


def test_history_projection_deduplicates_without_mutating_source():
    payload = history_payload()
    payload["chunks"].append(deepcopy(payload["chunks"][0]))
    original = deepcopy(payload)
    result = history_sync.project_history(payload)
    assert len(result.messages) == 2
    assert payload == original


def test_history_projection_rejects_conflicting_message_identity():
    payload = history_payload()
    conflict = deepcopy(payload["chunks"][0])
    conflict["threads"][0]["id"] = "another-customer"
    payload["chunks"].append(conflict)
    with pytest.raises(ValueError, match="Conflicting historical message"):
        history_sync.project_history(payload)


def test_history_projection_keeps_unmatched_media_separate():
    payload = {
        "chunks": [],
        "media_messages": [
            {
                "id": "media",
                "from": "business",
                "timestamp": "1739230970",
                "type": "image",
                "image": {"id": "asset"},
            }
        ],
    }
    result = history_sync.project_history(payload)
    assert result.messages == ()
    assert result.media_updates[0]["id"] == "media"


def test_history_projection_does_not_treat_decline_as_completion():
    result = history_sync.project_history(
        {"chunks": [{"errors": [{"code": 2593109}]}], "media_messages": []}
    )
    assert result.errors == ({"code": 2593109},)
    assert result.progress == result.messages == ()
