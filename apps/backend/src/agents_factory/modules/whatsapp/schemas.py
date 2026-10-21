from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class MetaWebhookModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class MetaMetadata(MetaWebhookModel):
    display_phone_number: str | None = None
    phone_number_id: str = Field(min_length=1, max_length=200)


class MetaInboundMessage(MetaWebhookModel):
    id: str = Field(min_length=1, max_length=500)
    sender_phone_number: str | None = Field(
        default=None, validation_alias="from", exclude=True
    )
    sender_user_id: str | None = Field(default=None, alias="from_user_id")
    sender_wa_id: str = Field(
        alias="from",
        validation_alias=AliasChoices("from", "from_user_id"),
        min_length=1,
        max_length=100,
    )
    # Retain signed live messages with unknown time; admission must deny them.
    # History and mobile echoes retain their strict timestamp contracts.
    timestamp: object | None = None
    type: str = Field(min_length=1, max_length=100)


class MetaMobileEcho(MetaInboundMessage):
    timestamp: str = Field(min_length=1, max_length=20)
    recipient_wa_id: str = Field(alias="to", min_length=1, max_length=100)


class MetaPricing(MetaWebhookModel):
    billable: bool | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    pricing_model: str | None = Field(default=None, min_length=1, max_length=100)


class MetaDeliveryError(MetaWebhookModel):
    code: int | str


class MetaDeliveryStatus(MetaWebhookModel):
    id: str = Field(min_length=1, max_length=500)
    recipient_id: str = Field(
        validation_alias=AliasChoices("recipient_id", "recipient_user_id"),
        min_length=1,
        max_length=100,
    )
    status: str = Field(min_length=1, max_length=100)
    timestamp: str = Field(min_length=1, max_length=20)
    pricing: MetaPricing | None = None
    errors: list[MetaDeliveryError] = Field(default_factory=list)


class MetaSyncedContact(MetaWebhookModel):
    phone_number: str = Field(min_length=1, max_length=100)
    full_name: str | None = Field(default=None, max_length=1000)
    first_name: str | None = Field(default=None, max_length=1000)


class MetaSyncTimestamp(MetaWebhookModel):
    timestamp: str = Field(min_length=1, max_length=20)


class MetaContactChange(MetaWebhookModel):
    type: Literal["contact"]
    action: Literal["add", "remove"]
    contact: MetaSyncedContact
    metadata: MetaSyncTimestamp


class MetaHistoryProgress(MetaWebhookModel):
    phase: int = Field(ge=0, le=2, strict=True)
    chunk_order: int = Field(ge=0, strict=True)
    progress: int = Field(ge=0, le=100, strict=True)


class MetaHistoryThread(MetaWebhookModel):
    id: str = Field(min_length=1, max_length=100)
    messages: list[MetaInboundMessage]


class MetaHistoryChunk(MetaWebhookModel):
    metadata: MetaHistoryProgress
    threads: list[MetaHistoryThread]


class MetaHistoryFailure(MetaWebhookModel):
    errors: list[MetaDeliveryError] = Field(min_length=1)


class MetaChangeValue(MetaWebhookModel):
    messaging_product: Literal["whatsapp"]
    metadata: MetaMetadata
    messages: list[MetaInboundMessage] = Field(default_factory=list)
    statuses: list[MetaDeliveryStatus] = Field(default_factory=list)
    message_echoes: list[MetaMobileEcho] = Field(default_factory=list)
    state_sync: list[MetaContactChange] = Field(default_factory=list)
    history: list[MetaHistoryChunk | MetaHistoryFailure] = Field(default_factory=list)


class MetaAccountUpdateValue(MetaWebhookModel):
    event: str = Field(min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, max_length=100)


class MetaChange(MetaWebhookModel):
    field: str
    value: MetaChangeValue | MetaAccountUpdateValue


class MetaEntry(MetaWebhookModel):
    id: str = Field(min_length=1, max_length=200)
    time: int | None = Field(default=None, ge=0, strict=True)
    changes: list[MetaChange]


class MetaWebhookPayload(MetaWebhookModel):
    object: Literal["whatsapp_business_account"]
    entry: list[MetaEntry]
