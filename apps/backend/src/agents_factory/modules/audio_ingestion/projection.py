"""Pure transcript projection; original audio and signed payload stay unchanged."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID
from .models import AudioTranscript


@dataclass(frozen=True, slots=True)
class EffectiveAudioMessage:
    text: str | None
    source_kind: Literal["TEXT", "AUDIO_TRANSCRIPT"] | None
    transcription_id: UUID | None = None
    digest: str | None = None
    state: str | None = None


def effective_message(
    row: Mapping[str, object], transcript: AudioTranscript | None
) -> EffectiveAudioMessage:
    if row.get("message_type") == "audio":
        state, ident = row.get("audio_state"), row.get("transcription_id")
        if state == "READY" and isinstance(ident, UUID) and transcript is not None:
            if row.get("transcription_digest") != transcript.digest:
                raise ValueError("audio_transcript_integrity_failed")
            return EffectiveAudioMessage(
                transcript.text, "AUDIO_TRANSCRIPT", ident, transcript.digest, "READY"
            )
        return EffectiveAudioMessage(
            None,
            None,
            ident if isinstance(ident, UUID) else None,
            None,
            state if isinstance(state, str) else None,
        )
    content = row.get("content")
    candidate = content.get("text") if isinstance(content, Mapping) else None
    return (
        EffectiveAudioMessage(candidate, "TEXT")
        if isinstance(candidate, str) and candidate.strip()
        else EffectiveAudioMessage(None, None)
    )
