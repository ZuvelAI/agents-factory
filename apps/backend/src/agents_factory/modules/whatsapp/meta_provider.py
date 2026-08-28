from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Mapping, cast
from uuid import UUID

import httpx
from pydantic import SecretStr, ValidationError

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.whatsapp.contracts import (
    DeliveryStatus,
    InboundWhatsAppEvent,
    MetaAccessTokenResolver,
    OutboundTemplateRequest,
    OutboundTextRequest,
    ProviderMessageResult,
    ProviderWebhookBatch,
    WhatsAppDeliveryStatusEvent,
    WhatsAppMessageType,
)
from agents_factory.modules.whatsapp.schemas import MetaWebhookPayload


_SIGNATURE_PATTERN = re.compile(r"sha256=([0-9a-f]{64})")
_SUPPORTED_MESSAGE_TYPES = frozenset(
    {"text", "audio", "image", "document", "location", "contacts", "video"}
)
_SUPPORTED_DELIVERY_STATUSES = frozenset(
    {"sent", "delivered", "read", "failed", "deleted"}
)


class InvalidWebhookPayload(DomainError):
    def __init__(self) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/invalid-webhook-payload",
            title="Invalid Webhook Payload",
            status=400,
            detail="The webhook payload is not supported.",
            code="invalid_webhook_payload",
        )


@dataclass(frozen=True, slots=True)
class MetaCloudApiProvider:
    app_secret: SecretStr = field(repr=False)
    access_tokens: MetaAccessTokenResolver | None = field(default=None, repr=False)
    http_client: httpx.AsyncClient | None = field(default=None, repr=False)
    graph_api_base_url: str | None = None

    def verify_signature(self, *, raw_body: bytes, signature: str) -> bool:
        match = _SIGNATURE_PATTERN.fullmatch(signature)
        if match is None:
            return False
        expected = hmac.new(
            self.app_secret.get_secret_value().encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(match.group(1), expected)

    def parse_webhook(
        self,
        payload: Mapping[str, object],
    ) -> ProviderWebhookBatch:
        try:
            parsed = MetaWebhookPayload.model_validate(payload)
        except ValidationError:
            raise InvalidWebhookPayload from None

        raw_payload = dict(payload)
        inbound_events: list[InboundWhatsAppEvent] = []
        delivery_statuses: list[WhatsAppDeliveryStatusEvent] = []
        for entry in parsed.entry:
            for change in entry.changes:
                if change.field != "messages":
                    continue
                for message in change.value.messages:
                    if message.type not in _SUPPORTED_MESSAGE_TYPES:
                        raise InvalidWebhookPayload
                    inbound_events.append(
                        InboundWhatsAppEvent(
                            waba_id=entry.id,
                            phone_number_id=change.value.metadata.phone_number_id,
                            whatsapp_message_id=message.id,
                            sender_wa_id=message.sender_wa_id,
                            message_type=cast(WhatsAppMessageType, message.type),
                            content=_normalized_content(message.model_dump()),
                            occurred_at=_provider_timestamp(message.timestamp),
                            raw_payload=raw_payload,
                        )
                    )
                for status in change.value.statuses:
                    if status.status not in _SUPPORTED_DELIVERY_STATUSES:
                        raise InvalidWebhookPayload
                    delivery_statuses.append(
                        WhatsAppDeliveryStatusEvent(
                            waba_id=entry.id,
                            phone_number_id=change.value.metadata.phone_number_id,
                            whatsapp_message_id=status.id,
                            recipient_wa_id=status.recipient_id,
                            status=cast(DeliveryStatus, status.status),
                            occurred_at=_provider_timestamp(status.timestamp),
                            raw_payload=raw_payload,
                            error_code=_delivery_error_code(status.errors),
                            cost_attribution=_cost_attribution(status.pricing),
                        )
                    )
        return ProviderWebhookBatch(
            inbound_events=tuple(inbound_events),
            delivery_statuses=tuple(delivery_statuses),
        )

    async def send_text(
        self,
        request: OutboundTextRequest,
    ) -> ProviderMessageResult:
        return await self._send(
            context=request.context,
            whatsapp_account_id=request.whatsapp_account_id,
            phone_number_id=request.phone_number_id,
            payload={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": request.recipient_wa_id,
                "type": "text",
                "text": {"preview_url": False, "body": request.body},
            },
        )

    async def send_template(
        self,
        request: OutboundTemplateRequest,
    ) -> ProviderMessageResult:
        template: dict[str, object] = {
            "name": request.template_name,
            "language": {"code": request.language},
        }
        if request.body_parameters:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": value}
                        for value in request.body_parameters
                    ],
                }
            ]
        return await self._send(
            context=request.context,
            whatsapp_account_id=request.whatsapp_account_id,
            phone_number_id=request.phone_number_id,
            payload={
                "messaging_product": "whatsapp",
                "to": request.recipient_wa_id,
                "type": "template",
                "template": template,
            },
        )

    async def _send(
        self,
        *,
        context: TenantContext,
        whatsapp_account_id: UUID,
        phone_number_id: str,
        payload: dict[str, object],
    ) -> ProviderMessageResult:
        if self.access_tokens is None or self.graph_api_base_url is None:
            return ProviderMessageResult(
                outcome="rejected",
                error_code="provider_not_configured",
            )
        resolved = await self.access_tokens.resolve(
            context=context,
            whatsapp_account_id=whatsapp_account_id,
        )
        try:
            access_token = resolved.reveal().decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return ProviderMessageResult(
                outcome="rejected",
                error_code="provider_credential_invalid",
            )
        url = f"{self.graph_api_base_url.rstrip('/')}/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            if self.http_client is None:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(url, headers=headers, json=payload)
            else:
                response = await self.http_client.post(
                    url,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException:
            return ProviderMessageResult(
                outcome="uncertain",
                error_code="provider_timeout",
            )
        except httpx.RequestError:
            return ProviderMessageResult(
                outcome="uncertain",
                error_code="provider_network_error",
            )
        return _provider_result(response)


def _provider_timestamp(value: str) -> datetime:
    try:
        seconds = int(value)
        if seconds < 0:
            raise ValueError
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, ValueError):
        raise InvalidWebhookPayload from None


def _normalized_content(message: Mapping[str, object]) -> dict[str, object]:
    message_type = message.get("type")
    if message_type != "text":
        return {}
    text_content = message.get("text")
    if not isinstance(text_content, dict):
        raise InvalidWebhookPayload
    body = text_content.get("body")
    if not isinstance(body, str) or not body.strip():
        raise InvalidWebhookPayload
    return {"text": body}


def _provider_result(response: httpx.Response) -> ProviderMessageResult:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if 200 <= response.status_code < 300:
        if isinstance(payload, Mapping):
            messages = payload.get("messages")
            if isinstance(messages, list) and messages:
                first = messages[0]
                if isinstance(first, Mapping):
                    provider_id = first.get("id")
                    if isinstance(provider_id, str) and provider_id.strip():
                        return ProviderMessageResult(
                            outcome="accepted",
                            provider_message_id=provider_id,
                        )
        return ProviderMessageResult(
            outcome="uncertain",
            error_code="invalid_provider_response",
        )
    error_code = f"http_{response.status_code}"
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            if isinstance(code, (int, str)):
                error_code = f"meta_{str(code)[:100]}"
    return ProviderMessageResult(
        outcome="uncertain" if response.status_code >= 500 else "rejected",
        error_code=error_code,
    )


def _delivery_error_code(errors: Sequence[object]) -> str | None:
    if not errors:
        return None
    code = getattr(errors[0], "code", None)
    if not isinstance(code, (int, str)):
        return None
    return f"meta_{str(code)[:100]}"


def _cost_attribution(pricing: object) -> dict[str, object]:
    if pricing is None:
        return {}
    result: dict[str, object] = {}
    for name in ("billable", "category", "pricing_model"):
        value = getattr(pricing, name, None)
        if isinstance(value, (bool, str)):
            result[name] = value
    return result
