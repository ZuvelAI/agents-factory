from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from apps.backend.tests.media_support import png, wav, pdf, mp4
from agents_factory.common.context import TenantContext
from agents_factory.modules.media.contact import normalize_contacts
from agents_factory.modules.media.contracts import MediaError
from agents_factory.modules.media.image import (
    ImageObservation,
    OpenAIImageObservationProvider,
)
from agents_factory.modules.media.location import normalize_location
from agents_factory.modules.media.metrics import word_error_rate, latency_percentiles
from agents_factory.modules.media.validation import sniff
from agents_factory.modules.media.voice import OpenAISpeechToTextProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.whatsapp.meta_provider import (
    MetaCloudApiProvider,
    _normalized_content,
)


def test_types_structured_payloads_and_measurement_functions():
    for kind, data, mime in (
        ("image", png(), "image/png"),
        ("audio", wav(), "audio/wav"),
        ("document", pdf(), "application/pdf"),
        ("video", mp4(), "video/mp4"),
    ):
        assert sniff(data, claimed=mime, kind=kind) == mime
        with pytest.raises(MediaError):
            sniff(data[:10], claimed=mime, kind=kind)
        with pytest.raises(MediaError):
            sniff(data, claimed="application/octet-stream", kind=kind)
    with pytest.raises(MediaError, match="size"):
        sniff(b"x" * (20 * 1024 * 1024 + 1), claimed="image/png", kind="image")
    with pytest.raises(ValidationError):
        normalize_location({"latitude": float("nan"), "longitude": 0})
    location = normalize_location(
        {"latitude": 4.71, "longitude": -74.07, "address": "Bogota"}
    )
    contact = {
        "name": {"formatted_name": "Fixture"},
        "phones": [{"phone": "+573000000027"}],
        "emails": [{"email": "fixture@example.com"}],
        "org": {"company": "Fixture"},
    }
    contacts = normalize_contacts({"contacts": [contact]})
    assert contacts.fields["contacts"][0]["emails"] == contact["emails"]
    assert location.identity_level_delta == contacts.identity_level_delta == 0
    for kind, raw in (
        ("audio", {"id": "2", "mime_type": "audio/wav", "url": "https://evil.invalid"}),
        ("image", {"id": "1", "caption": "claim"}),
        ("document", {"id": "3"}),
        ("video", {"id": "4"}),
    ):
        normalized = _normalized_content({"type": kind, kind: raw})
        assert normalized["id"] == raw["id"] and "url" not in normalized
    assert _normalized_content({"type": "contacts", "contacts": [contact]}) == {
        "contacts": [contact]
    }
    assert word_error_rate("Quiero cambiar mi cita", "quiero cambiar la cita") == 0.25
    assert word_error_rate("Order twenty seven", "Order twenty seven") == 0
    assert latency_percentiles((10, 20, 30, 40)) == {"p50": 20, "p95": 40}


async def test_meta_download_and_openai_adapters_use_bounded_typed_contracts():
    data = png()
    requested = []
    target = ["https://lookaside.fbsbx.com/whatsapp_business/attachments/?id=1"]

    def respond(request):
        requested.append(request)
        if request.url.host == "graph.facebook.com":
            assert request.url.params["phone_number_id"] == "27"
            return httpx.Response(
                200,
                json={
                    "id": "1",
                    "url": target[0],
                    "file_size": len(data),
                    "mime_type": "image/png",
                    "sha256": base64.b64encode(hashlib.sha256(data).digest()).decode(),
                },
            )
        return httpx.Response(200, content=data)

    access = SimpleNamespace(
        resolve=AsyncMock(return_value=ResolvedSecret(b"fixture-authorization-only"))
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = MetaCloudApiProvider(
            SecretStr("fixture"),
            access_tokens=access,
            http_client=client,
            graph_api_base_url="https://graph.facebook.com/v23.0",
        )
        args = dict(
            context=TenantContext(uuid4(), uuid4(), "system", uuid4()),
            whatsapp_account_id=uuid4(),
            phone_number_id="27",
            media_id="1",
            max_bytes=1024,
        )
        assert await provider.download_media(**args) == (data, "image/png")
        target[0] = "http://127.0.0.1/private"
        with pytest.raises(MediaError, match="host_denied"):
            await provider.download_media(**args)
        assert (
            len(requested) == 3
        )  # denied before a second download/credential transfer
        with pytest.raises(MediaError, match="reference_invalid"):
            await provider.download_media(**{**args, "media_id": "../private"})

    transcribe = AsyncMock(
        return_value=SimpleNamespace(
            text="Mi pedido llegó dañado",
            model_dump=lambda: {"usage": {"input_tokens": 12, "output_tokens": 5}},
        )
    )
    parsed = ImageObservation(
        description="A dented box",
        visible_text="27",
        visible_damage=("dent",),
        uncertain_details=("contents unknown",),
    )
    inspect_image = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=30, output_tokens=20),
        )
    )
    sdk = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=transcribe)),
        responses=SimpleNamespace(parse=inspect_image),
    )
    options = []
    sdk.with_options = lambda **kwargs: (options.append(kwargs), sdk)[1]
    voice = await OpenAISpeechToTextProvider(sdk).normalize(
        wav(), media_type="audio/wav", language="es", vocabulary=("Zuvel", "pedido")
    )
    image = await OpenAIImageObservationProvider(sdk).normalize(
        data, media_type="image/png", language="en", vocabulary=()
    )
    assert voice.text == "Mi pedido llegó dañado" and voice.usage.cost_usd is None
    assert transcribe.call_args.kwargs["model"] == "gpt-4o-mini-transcribe"
    assert transcribe.call_args.kwargs["response_format"] == "json"
    assert "Zuvel" in transcribe.call_args.kwargs["prompt"]
    assert image.fields["visible_damage"] == ["dent"]
    assert inspect_image.call_args.kwargs["tools"] == []
    assert inspect_image.call_args.kwargs["store"] is False
    assert inspect_image.call_args.kwargs["model"] == "gpt-5.6-luna"
    assert all(option["max_retries"] == 0 for option in options)
    assert voice.identity_level_delta == image.identity_level_delta == 0
