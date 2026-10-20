from uuid import uuid4

import pytest

from agents_factory.modules.audio_ingestion.models import (
    AudioTranscript,
    TRANSCRIPTION_MODEL,
)
from agents_factory.modules.audio_ingestion.projection import effective_message


def test_ready_projection_requires_transcription_digest_match():
    transcript = AudioTranscript("Consulta", TRANSCRIPTION_MODEL)
    row = {
        "message_type": "audio",
        "audio_state": "READY",
        "transcription_id": uuid4(),
        "transcription_digest": "0" * 64,
    }
    with pytest.raises(ValueError, match="audio_transcript_integrity_failed"):
        effective_message(row, transcript)
    row["transcription_digest"] = transcript.digest
    assert effective_message(row, transcript).source_kind == "AUDIO_TRANSCRIPT"


@pytest.mark.parametrize(
    "state", [None, "QUEUED", "PROCESSING", "FAILED", "CANCELLED", "UNCERTAIN"]
)
def test_non_ready_audio_never_uses_a_forged_text_field(state):
    row = {
        "message_type": "audio",
        "audio_state": state,
        "content": {"text": "Not an actual transcript"},
    }
    assert effective_message(row, None).text is None
