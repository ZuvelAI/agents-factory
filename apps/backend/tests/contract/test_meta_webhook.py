from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agents_factory.config import Settings
from agents_factory.main import ReadinessChecks, create_app
from agents_factory.modules.whatsapp.contracts import WebhookProcessingResult
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.webhook import (
    WebhookProcessor,
    get_meta_webhook_processor,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "meta"
SUPPORTED_MESSAGE_TYPES = (
    "text",
    "audio",
    "image",
    "document",
    "location",
    "contacts",
    "video",
)


async def _ready() -> None:
    return None


def _settings() -> Settings:
    return Settings(
        environment="test",
        log_level="info",
        database_url=SecretStr("postgresql+asyncpg://app:secret@database/app"),
        redis_url=SecretStr("redis://:secret@redis:6379/0"),
        supabase_url="https://example.supabase.co",
        supabase_publishable_key=SecretStr("publishable-secret"),
        supabase_jwt_issuer="https://example.supabase.co/auth/v1",
        supabase_jwt_audience="authenticated",
        app_master_key=SecretStr("master-secret"),
        meta_app_secret=SecretStr("meta-app-secret"),
        meta_webhook_verify_token=SecretStr("verify-token"),
    )


class _RecordingProcessor:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, UUID]] = []

    async def process(
        self,
        *,
        raw_body: bytes,
        signature: str,
        correlation_id: UUID,
    ) -> WebhookProcessingResult:
        self.calls.append((raw_body, signature, correlation_id))
        return WebhookProcessingResult(
            accepted_messages=1,
            duplicate_messages=0,
            delivery_statuses=0,
        )


def _client(processor: _RecordingProcessor | None = None) -> TestClient:
    application = create_app(
        settings_loader=_settings,
        readiness_checks=ReadinessChecks(database=_ready, redis=_ready),
    )
    if processor is not None:

        async def override_processor() -> WebhookProcessor:
            return cast(WebhookProcessor, processor)

        application.dependency_overrides[get_meta_webhook_processor] = (
            override_processor
        )
    return TestClient(application)


def _payload(name: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((FIXTURES / name).read_text(encoding="utf-8")),
    )


def test_verification_challenge_is_returned_only_for_the_configured_token() -> None:
    with _client() as client:
        accepted = client.get(
            "/webhooks/meta/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-token",
                "hub.challenge": "123456789",
            },
        )
        denied = client.get(
            "/webhooks/meta/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "123456789",
            },
        )

    assert accepted.status_code == 200
    assert accepted.text == "123456789"
    assert accepted.headers["content-type"].startswith("text/plain")
    assert denied.status_code == 403
    assert "verify-token" not in denied.text
    assert "wrong-token" not in denied.text


def test_post_passes_exact_raw_bytes_and_signature_to_the_processor() -> None:
    processor = _RecordingProcessor()
    raw_body = b'{ "object": "whatsapp_business_account", "entry": [] }\n'

    with _client(processor) as client:
        response = client.post(
            "/webhooks/meta/whatsapp",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=" + "a" * 64,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "accepted_messages": 1,
        "duplicate_messages": 0,
        "delivery_statuses": 0,
    }
    assert len(processor.calls) == 1
    received_body, received_signature, correlation_id = processor.calls[0]
    assert received_body == raw_body
    assert received_signature == "sha256=" + "a" * 64
    assert correlation_id.version == 7


def test_missing_signature_is_rejected_before_processing() -> None:
    processor = _RecordingProcessor()

    with _client(processor) as client:
        response = client.post(
            "/webhooks/meta/whatsapp",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 401
    assert processor.calls == []


@pytest.mark.parametrize("message_type", SUPPORTED_MESSAGE_TYPES)
def test_provider_normalizes_each_v1_inbound_message_type(message_type: str) -> None:
    payload = deepcopy(_payload("inbound_text.json"))
    entry = cast(dict[str, object], cast(list[object], payload["entry"])[0])
    change = cast(dict[str, object], cast(list[object], entry["changes"])[0])
    value = cast(dict[str, object], change["value"])
    inbound = cast(dict[str, object], cast(list[object], value["messages"])[0])
    inbound.pop("text", None)
    inbound["type"] = message_type
    inbound[message_type] = (
        {"body": "Hola"}
        if message_type == "text"
        else {"id": f"media-{message_type}-001"}
    )
    if message_type == "location":
        inbound[message_type] = {"latitude": 4.7, "longitude": -74.1}
    if message_type == "contacts":
        inbound[message_type] = [{"name": {"formatted_name": "Persona"}}]
    provider = MetaCloudApiProvider(app_secret=SecretStr("meta-app-secret"))

    batch = provider.parse_webhook(payload)

    assert len(batch.inbound_events) == 1
    event = batch.inbound_events[0]
    assert event.waba_id == "waba_test_001"
    assert event.phone_number_id == "phone_number_test_001"
    assert event.whatsapp_message_id == "wamid.test.inbound.001"
    assert event.sender_wa_id == "573000000001"
    assert event.message_type == message_type
    assert event.content == ({"text": "Hola"} if message_type == "text" else {})
    assert event.occurred_at.isoformat() == "2026-08-27T00:00:00+00:00"
    assert batch.delivery_statuses == ()


def test_provider_normalizes_delivery_status_without_treating_it_as_inbound() -> None:
    provider = MetaCloudApiProvider(app_secret=SecretStr("meta-app-secret"))

    batch = provider.parse_webhook(_payload("delivery_status.json"))

    assert batch.inbound_events == ()
    assert len(batch.delivery_statuses) == 1
    delivery = batch.delivery_statuses[0]
    assert delivery.waba_id == "waba_test_001"
    assert delivery.phone_number_id == "phone_number_test_001"
    assert delivery.whatsapp_message_id == "wamid.test.outbound.001"
    assert delivery.recipient_wa_id == "573000000001"
    assert delivery.status == "delivered"
    assert delivery.occurred_at.isoformat() == "2026-08-27T00:01:00+00:00"
    assert delivery.cost_attribution == {
        "billable": True,
        "category": "service",
        "pricing_model": "CBP",
    }
