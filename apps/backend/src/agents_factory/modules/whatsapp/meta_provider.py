from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Mapping, cast

from pydantic import SecretStr, ValidationError

from agents_factory.common.errors import DomainError
from agents_factory.modules.whatsapp.contracts import (
    DeliveryStatus,
    InboundWhatsAppEvent,
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
                        )
                    )
        return ProviderWebhookBatch(
            inbound_events=tuple(inbound_events),
            delivery_statuses=tuple(delivery_statuses),
        )


def _provider_timestamp(value: str) -> datetime:
    try:
        seconds = int(value)
        if seconds < 0:
            raise ValueError
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, ValueError):
        raise InvalidWebhookPayload from None
