import pytest

from agents_factory.modules.audio_ingestion.models import (
    AudioInspection,
    AudioTranscript,
)


@pytest.mark.parametrize(
    "seconds,size", [(300.001, 1), (1, 10_000_001), (float("nan"), 1), (0, 1), (1, 0)]
)
def test_inspection_rejects_outside_bounds(seconds, size):
    with pytest.raises(ValueError):
        AudioInspection(
            container="ogg", codec="opus", duration_seconds=seconds, size_bytes=size
        )


def test_inspection_accepts_exact_limits_but_not_other_codecs():
    inspection = AudioInspection(
        container="ogg", codec="opus", duration_seconds=300, size_bytes=10_000_000
    )
    assert inspection.duration_seconds == 300
    with pytest.raises(ValueError):
        AudioInspection(
            container="ogg", codec="vorbis", duration_seconds=1, size_bytes=10
        )


@pytest.mark.parametrize("body", ["", " \n ", "x" * 25_001])
def test_transcript_rejects_empty_or_excessive_content(body):
    with pytest.raises(ValueError):
        AudioTranscript(text=body, model="gpt-4o-mini-transcribe-2025-12-15")


def test_transcript_digest_covers_exact_retained_text():
    transcript = AudioTranscript(text="hola", model="gpt-4o-mini-transcribe-2025-12-15")
    assert (
        transcript.digest
        == "b221d9dbb083a7f33428d7c2a3c3198ae925614d70210e28716ccaa7cd4ddb79"
    )
