import base64

import pytest

from agents_factory.modules.whatsapp.meta_provider import (
    _normalized_content,
    InvalidWebhookPayload,
)


def test_audio_normalization_keeps_only_signed_media_fields():
    audio = {
        "id": "123456",
        "mime_type": "audio/ogg; codecs=opus",
        "sha256": base64.b64encode(b"x" * 32).decode(),
        "url": "https://evil.example",
        "voice": True,
    }
    content = _normalized_content({"type": "audio", "audio": audio})
    assert content == {
        "audio": {key: audio[key] for key in ("id", "mime_type", "sha256")}
    }


@pytest.mark.parametrize(
    "audio",
    [
        {},
        {"id": "../token", "mime_type": "audio/ogg"},
        {"id": "123", "mime_type": "a" * 101},
        {"id": "123", "mime_type": "audio/ogg", "sha256": "not-base64"},
    ],
)
def test_audio_normalization_rejects_invalid_signed_metadata(audio):
    with pytest.raises(InvalidWebhookPayload):
        _normalized_content({"type": "audio", "audio": audio})


@pytest.mark.parametrize("kind", ["image", "video", "document", "location", "contacts"])
def test_other_media_does_not_enter_audio_normalization(kind):
    assert _normalized_content({"type": kind, "audio": {"id": "123"}}) == {}


def test_voice_settings_default_on_and_emergency_switch(monkeypatch):
    from apps.backend.tests.unit.test_config import _valid_environment
    from agents_factory.config import load_settings

    for name, value in _valid_environment().items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("WHATSAPP_AUDIO_ENABLED", raising=False)
    assert load_settings().whatsapp_audio_enabled is True
    monkeypatch.setenv("WHATSAPP_AUDIO_ENABLED", "false")
    assert load_settings().whatsapp_audio_enabled is False


async def test_worker_registers_shared_audio_and_keeps_provider_lazy(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from apps.backend.tests.unit.test_config import _valid_environment
    from agent_worker import jobs

    for name, value in _valid_environment().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(
        "APP_MASTER_KEY", base64.urlsafe_b64encode(b"x" * 32).rstrip(b"=").decode()
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine = create_async_engine(_valid_environment()["DATABASE_URL"])
    context = {
        "database": SimpleNamespace(session_factory=async_sessionmaker(engine)),
        "redis": AsyncMock(),
        "job_handlers": {},
    }
    monkeypatch.setattr(jobs, "configure_durable_worker", AsyncMock())
    try:
        await jobs.configure_agent_worker(context)
        assert "whatsapp.audio.transcribe" in context["job_handlers"]
        assert context["durable_job_runner"]._preflight is not None
        assert (
            context["job_handlers"][
                "whatsapp.audio.transcribe"
            ].__self__.transcriber.client
            is None
        )
    finally:
        await engine.dispose()


async def test_worker_deferral_keeps_five_second_delay(monkeypatch):
    from unittest.mock import AsyncMock
    from arq import Retry
    from agent_worker import worker
    from agents_factory.common.queue import JobRunResult

    monkeypatch.setattr(
        worker,
        "run_registered_job",
        AsyncMock(return_value=JobRunResult("deferred", None, 5)),
    )
    with pytest.raises(Retry) as caught:
        await worker.process_job({}, {})
    assert caught.value.defer_score == 5000
