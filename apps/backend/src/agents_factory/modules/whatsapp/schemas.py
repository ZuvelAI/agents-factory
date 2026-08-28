from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MetaWebhookModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class MetaMetadata(MetaWebhookModel):
    display_phone_number: str | None = None
    phone_number_id: str = Field(min_length=1, max_length=200)


class MetaInboundMessage(MetaWebhookModel):
    id: str = Field(min_length=1, max_length=500)
    sender_wa_id: str = Field(alias="from", min_length=1, max_length=100)
    timestamp: str = Field(min_length=1, max_length=20)
    type: str = Field(min_length=1, max_length=100)


class MetaPricing(MetaWebhookModel):
    billable: bool | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    pricing_model: str | None = Field(default=None, min_length=1, max_length=100)


class MetaDeliveryError(MetaWebhookModel):
    code: int | str


class MetaDeliveryStatus(MetaWebhookModel):
    id: str = Field(min_length=1, max_length=500)
    recipient_id: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=100)
    timestamp: str = Field(min_length=1, max_length=20)
    pricing: MetaPricing | None = None
    errors: list[MetaDeliveryError] = Field(default_factory=list)


class MetaChangeValue(MetaWebhookModel):
    messaging_product: Literal["whatsapp"]
    metadata: MetaMetadata
    messages: list[MetaInboundMessage] = Field(default_factory=list)
    statuses: list[MetaDeliveryStatus] = Field(default_factory=list)


class MetaChange(MetaWebhookModel):
    field: str
    value: MetaChangeValue


class MetaEntry(MetaWebhookModel):
    id: str = Field(min_length=1, max_length=200)
    changes: list[MetaChange]


class MetaWebhookPayload(MetaWebhookModel):
    object: Literal["whatsapp_business_account"]
    entry: list[MetaEntry]
