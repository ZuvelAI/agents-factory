from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agents_factory.modules.audio_ingestion.models import (
    AudioInspection,
    TRANSCRIPTION_MODEL,
)
from agents_factory.modules.audio_ingestion.transcriber import (
    OpenAIAudioTranscriber,
    AudioTranscriptionError,
)


async def test_transcriber_uses_fixed_model_without_sdk_retries(tmp_path):
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"synthetic")
    create = AsyncMock(
        return_value=SimpleNamespace(
            text="Quiero un agente", usage=None, model_extra={}
        )
    )
    client = Mock()
    client.with_options.return_value.audio.transcriptions.create = create
    result = await OpenAIAudioTranscriber(client).transcribe(
        path, AudioInspection("ogg", "opus", 1, 9)
    )
    assert result.text == "Quiero un agente"
    assert result.model == TRANSCRIPTION_MODEL
    client.with_options.assert_called_once_with(timeout=60.0, max_retries=0)
    assert create.call_args.kwargs["model"] == TRANSCRIPTION_MODEL
    assert create.call_args.kwargs["response_format"] == "json"
    assert create.call_args.kwargs["file"].closed


@pytest.mark.parametrize(
    "payload",
    [
        {"text": " "},
        {"text": "a" * 25001},
        {"text": "partial", "truncated": True},
        {"text": "partial", "finish_reason": "length"},
    ],
)
async def test_silent_audio_with_empty_transcript_never_enters_agent_turn(
    tmp_path, payload
):
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"synthetic")
    client = Mock()
    client.with_options.return_value.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(**payload, usage=None, model_extra=payload)
    )
    with pytest.raises(AudioTranscriptionError, match="audio_transcription_invalid"):
        await OpenAIAudioTranscriber(client).transcribe(
            path, AudioInspection("ogg", "opus", 1, 9)
        )


async def test_provider_exception_is_safe_and_not_retried(tmp_path):
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"synthetic")
    create = AsyncMock(side_effect=RuntimeError("PRIVATE token and transcript"))
    client = Mock()
    client.with_options.return_value.audio.transcriptions.create = create
    with pytest.raises(AudioTranscriptionError) as caught:
        await OpenAIAudioTranscriber(client).transcribe(
            path, AudioInspection("ogg", "opus", 1, 9)
        )
    assert str(caught.value) == "audio_transcription_uncertain"
    assert caught.value.__suppress_context__
    assert create.await_count == 1
