"""Single paid attempt; uncertain network results are never retried here."""

import asyncio
from pathlib import Path

from openai import AsyncOpenAI

from .models import AudioInspection, AudioTranscript, TRANSCRIPTION_MODEL


class AudioTranscriptionError(RuntimeError):
    pass


class OpenAIAudioTranscriber:
    def __init__(self, client: AsyncOpenAI) -> None:
        self.client = client

    async def transcribe(
        self, path: Path, inspection: AudioInspection
    ) -> AudioTranscript:
        if path.stat().st_size != inspection.size_bytes:
            raise AudioTranscriptionError("audio_transcription_invalid")
        try:
            async with asyncio.timeout(60):
                with path.open("rb") as audio:
                    result = await self.client.with_options(
                        timeout=60.0, max_retries=0
                    ).audio.transcriptions.create(
                        model=TRANSCRIPTION_MODEL, file=audio, response_format="json"
                    )
        except Exception:
            raise AudioTranscriptionError("audio_transcription_uncertain") from None
        extra = result.model_extra or {}
        if extra.get("truncated") or extra.get("finish_reason") in {
            "length",
            "max_tokens",
        }:
            raise AudioTranscriptionError("audio_transcription_invalid")
        usage = result.usage
        try:
            return AudioTranscript(
                result.text,
                TRANSCRIPTION_MODEL,
                getattr(usage, "input_tokens", None),
                getattr(usage, "output_tokens", None),
            )
        except (ValueError, TypeError, AttributeError):
            raise AudioTranscriptionError("audio_transcription_invalid") from None
