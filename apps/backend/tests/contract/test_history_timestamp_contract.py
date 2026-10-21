import pytest
from pydantic import ValidationError

from agents_factory.modules.whatsapp.history_sync import HistoryInboxPayload
from agents_factory.modules.whatsapp.schemas import MetaHistoryThread


@pytest.mark.parametrize("value", [None, {}, 123])
def test_history_and_archived_media_keep_required_string_timestamp(value):
    message = {
        "id": "synthetic",
        "from": "synthetic",
        "type": "text",
        "timestamp": value,
    }
    with pytest.raises(ValidationError):
        MetaHistoryThread.model_validate({"id": "synthetic", "messages": [message]})
    with pytest.raises(ValidationError):
        HistoryInboxPayload.model_validate({"chunks": [], "media_messages": [message]})
