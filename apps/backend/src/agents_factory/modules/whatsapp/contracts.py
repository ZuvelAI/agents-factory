from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Protocol


WhatsAppMessageType = Literal[
    "text",
    "audio",
    "image",
    "document",
    "location",
    "contacts",
    "video",
]
DeliveryStatus = Literal["sent", "delivered", "read", "failed", "deleted"]


@dataclass(frozen=True, slots=True)
class InboundWhatsAppEvent:
    waba_id: str
    phone_number_id: str
    whatsapp_message_id: str
    sender_wa_id: str
    message_type: WhatsAppMessageType
    occurred_at: datetime
    raw_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class WhatsAppDeliveryStatusEvent:
    waba_id: str
    phone_number_id: str
    whatsapp_message_id: str
    recipient_wa_id: str
    status: DeliveryStatus
    occurred_at: datetime
    raw_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class ProviderWebhookBatch:
    inbound_events: tuple[InboundWhatsAppEvent, ...]
    delivery_statuses: tuple[WhatsAppDeliveryStatusEvent, ...]


@dataclass(frozen=True, slots=True)
class WebhookProcessingResult:
    accepted_messages: int
    duplicate_messages: int
    delivery_statuses: int


class WhatsAppProvider(Protocol):
    """Inbound provider surface owned by Task 6.

    Outbound delivery and media methods are added by their owning v1 tasks.
    """

    def verify_signature(self, *, raw_body: bytes, signature: str) -> bool: ...

    def parse_webhook(
        self,
        payload: Mapping[str, object],
    ) -> ProviderWebhookBatch: ...
