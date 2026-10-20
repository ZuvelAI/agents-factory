"""Immutable, bounded audio contracts. No providers, SQL or credentials."""

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import math
from typing import Literal
from uuid import UUID

AudioTerminalState = Literal["FAILED", "CANCELLED", "UNCERTAIN"]
AudioState = Literal[
    "QUEUED", "PROCESSING", "READY", "FAILED", "CANCELLED", "UNCERTAIN"
]
AudioPhase = Literal["PREFLIGHT", "PROVIDER_STARTED"]
TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe-2025-12-15"


@dataclass(frozen=True, slots=True)
class AudioSource:
    tenant_id: UUID
    account_id: UUID
    conversation_id: UUID
    message_id: UUID
    event_id: UUID
    provider_message_id: str
    media_id: str
    mime_type: str
    expected_sha256: str | None
    arrival_sequence: int


@dataclass(frozen=True, slots=True)
class AudioClaim:
    transcription_id: UUID
    source: AudioSource
    lease_id: UUID
    owner_id: UUID
    first_claim_at: datetime
    deadline: datetime
    lease_expires_at: datetime
    phase: AudioPhase


@dataclass(frozen=True, slots=True)
class AudioInspection:
    container: str
    codec: str
    duration_seconds: float
    size_bytes: int

    def __post_init__(self) -> None:
        if self.container != "ogg" or self.codec != "opus":
            raise ValueError("audio_format_unsupported")
        if (
            not math.isfinite(self.duration_seconds)
            or not 0 < self.duration_seconds <= 300
        ):
            raise ValueError("audio_duration_invalid")
        if isinstance(self.size_bytes, bool) or not 0 < self.size_bytes <= 10_000_000:
            raise ValueError("audio_size_invalid")


@dataclass(frozen=True, slots=True)
class AudioTranscript:
    text: str = field(repr=False)
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.text.strip() or len(self.text) > 25_000:
            raise ValueError("audio_transcript_invalid")
        if self.model != TRANSCRIPTION_MODEL:
            raise ValueError("audio_model_unsupported")
        for value in (self.input_tokens, self.output_tokens):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError("audio_usage_invalid")

    @property
    def digest(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()
