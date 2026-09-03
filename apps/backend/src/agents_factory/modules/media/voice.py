from __future__ import annotations

import json
from time import perf_counter

from openai import AsyncOpenAI

from agents_factory.modules.media.contracts import (
    MediaError,
    MediaUsage,
    NormalizedMediaObservation,
)


class OpenAISpeechToTextProvider:
    model = "gpt-4o-mini-transcribe"

    def __init__(self, client: AsyncOpenAI) -> None:
        # Explicit client injection only: no automatic discovery/use of credentials.
        self.client = client.with_options(max_retries=0, timeout=30)

    async def normalize(
        self,
        content: bytes,
        *,
        media_type: str,
        language: str,
        vocabulary: tuple[str, ...],
    ) -> NormalizedMediaObservation:
        if language not in {"es", "en"}:
            raise MediaError("media_language_invalid")
        extension = {
            "audio/ogg": "ogg",
            "audio/wav": "wav",
            "audio/mp4": "m4a",
            "audio/mpeg": "mp3",
        }.get(media_type)
        if extension is None:
            raise MediaError("media_type_mismatch")
        started = perf_counter()
        try:
            result = await self.client.audio.transcriptions.create(
                file=(f"voice.{extension}", content, media_type),
                model=self.model,
                response_format="json",
                language=language,
                prompt=(
                    "Vocabulario del negocio: "
                    if language == "es"
                    else "Business vocabulary: "
                )
                + json.dumps(vocabulary[:100], ensure_ascii=False)[:4000],
            )
            payload = result.model_dump()
            usage = payload.get("usage") or {}
            return NormalizedMediaObservation(
                kind="audio",
                status="READY",
                text=result.text,
                usage=MediaUsage(
                    model=self.model,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    audio_seconds=usage.get("seconds"),
                    latency_ms=(perf_counter() - started) * 1000,
                    cost_basis="unpriced",
                ),
            )
        except Exception:
            raise MediaError("audio_processing_unconfirmed") from None
