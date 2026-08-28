from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Mapping, Protocol
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.modules.secrets.redaction import ResolvedSecret


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
ProviderMessageOutcome = Literal["accepted", "rejected", "uncertain"]


@dataclass(frozen=True, slots=True)
class InboundWhatsAppEvent:
    waba_id: str
    phone_number_id: str
    whatsapp_message_id: str
    sender_wa_id: str
    message_type: WhatsAppMessageType
    content: dict[str, object]
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
    error_code: str | None = None
    cost_attribution: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OutboundTextRequest:
    context: TenantContext
    whatsapp_account_id: UUID
    phone_number_id: str
    recipient_wa_id: str
    body: str
    client_reference: str


@dataclass(frozen=True, slots=True)
class OutboundTemplateRequest:
    context: TenantContext
    whatsapp_account_id: UUID
    phone_number_id: str
    recipient_wa_id: str
    template_name: str
    language: str
    body_parameters: tuple[str, ...]
    client_reference: str


@dataclass(frozen=True, slots=True)
class ProviderMessageResult:
    outcome: ProviderMessageOutcome
    provider_message_id: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.outcome == "accepted" and not self.provider_message_id:
            raise ValueError("accepted provider result requires a message id")
        if self.outcome != "accepted" and self.provider_message_id is not None:
            raise ValueError("non-accepted provider result cannot have a message id")


class MetaAccessTokenResolver(Protocol):
    async def resolve(
        self,
        *,
        context: TenantContext,
        whatsapp_account_id: UUID,
    ) -> ResolvedSecret: ...


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
    """Meta-independent WhatsApp boundary used by inbound and outbound flows."""

    def verify_signature(self, *, raw_body: bytes, signature: str) -> bool: ...

    def parse_webhook(
        self,
        payload: Mapping[str, object],
    ) -> ProviderWebhookBatch: ...

    async def send_text(
        self,
        request: OutboundTextRequest,
    ) -> ProviderMessageResult: ...

    async def send_template(
        self,
        request: OutboundTemplateRequest,
    ) -> ProviderMessageResult: ...
