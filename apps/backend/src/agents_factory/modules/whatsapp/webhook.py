from __future__ import annotations

import hmac
import json
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.outbox import OutboxService
from agents_factory.config import Settings
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.whatsapp.contracts import (
    WebhookProcessingResult,
    WhatsAppProvider,
)
from agents_factory.modules.whatsapp.meta_provider import (
    InvalidWebhookPayload,
    MetaCloudApiProvider,
)
from agents_factory.modules.whatsapp.repository import WhatsAppWebhookRepository


router = APIRouter(prefix="/webhooks/meta/whatsapp", tags=["meta-whatsapp"])


class InvalidWebhookSignature(DomainError):
    def __init__(self) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/invalid-webhook-signature",
            title="Invalid Webhook Signature",
            status=401,
            detail="The webhook signature is invalid.",
            code="invalid_webhook_signature",
        )


class UnknownAccountMapping(DomainError):
    def __init__(self) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/unknown-whatsapp-account",
            title="Unknown WhatsApp Account",
            status=404,
            detail="No active WhatsApp account mapping was found.",
            code="unknown_whatsapp_account",
        )


class WebhookVerificationDenied(DomainError):
    def __init__(self) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/webhook-verification-denied",
            title="Webhook Verification Denied",
            status=403,
            detail="Webhook verification was denied.",
            code="webhook_verification_denied",
        )


class WebhookAck(BaseModel):
    accepted_messages: int
    duplicate_messages: int
    delivery_statuses: int


class WebhookProcessor(Protocol):
    async def process(
        self,
        *,
        raw_body: bytes,
        signature: str,
        correlation_id: UUID,
    ) -> WebhookProcessingResult: ...


class MetaWebhookProcessor:
    def __init__(
        self,
        *,
        session: AsyncSession,
        provider: WhatsAppProvider,
    ) -> None:
        self._repository = WhatsAppWebhookRepository(session)
        self._outbox = OutboxService(session)
        self._provider = provider

    async def process(
        self,
        *,
        raw_body: bytes,
        signature: str,
        correlation_id: UUID,
    ) -> WebhookProcessingResult:
        if not self._provider.verify_signature(
            raw_body=raw_body,
            signature=signature,
        ):
            raise InvalidWebhookSignature
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InvalidWebhookPayload from None
        if not isinstance(payload, dict):
            raise InvalidWebhookPayload

        batch = self._provider.parse_webhook(payload)
        accepted_messages = 0
        duplicate_messages = 0
        for event in batch.inbound_events:
            mapping = await self._repository.resolve_active_mapping(
                waba_id=event.waba_id,
                phone_number_id=event.phone_number_id,
            )
            if mapping is None:
                raise UnknownAccountMapping
            context = TenantContext(
                tenant_id=mapping.tenant_id,
                actor_id=None,
                actor_type="system",
                correlation_id=correlation_id,
            )
            persisted = await self._repository.persist_inbound(
                context=context,
                mapping=mapping,
                event=event,
            )
            if not persisted.created:
                duplicate_messages += 1
                continue
            await self._outbox.enqueue(
                context=context,
                idempotency_key=f"whatsapp.inbound:{event.whatsapp_message_id}",
                topic="whatsapp.inbound.received",
                payload={
                    "aggregate_id": str(persisted.event_id),
                    "event_id": str(persisted.event_id),
                    "whatsapp_account_id": str(mapping.account_id),
                    "whatsapp_message_id": event.whatsapp_message_id,
                },
            )
            accepted_messages += 1

        for status in batch.delivery_statuses:
            mapping = await self._repository.resolve_active_mapping(
                waba_id=status.waba_id,
                phone_number_id=status.phone_number_id,
            )
            if mapping is None:
                raise UnknownAccountMapping

        return WebhookProcessingResult(
            accepted_messages=accepted_messages,
            duplicate_messages=duplicate_messages,
            delivery_statuses=len(batch.delivery_statuses),
        )


async def get_meta_webhook_processor(
    request: Request,
    session: TransactionSession,
) -> WebhookProcessor:
    settings: Settings = request.app.state.settings
    return MetaWebhookProcessor(
        session=session,
        provider=MetaCloudApiProvider(app_secret=settings.meta_app_secret),
    )


WebhookProcessorDependency = Annotated[
    WebhookProcessor,
    Depends(get_meta_webhook_processor),
]


@router.get("")
async def verify_webhook(
    request: Request,
    mode: Annotated[str, Query(alias="hub.mode", min_length=1, max_length=50)],
    verify_token: Annotated[
        str,
        Query(alias="hub.verify_token", min_length=1, max_length=500),
    ],
    challenge: Annotated[
        str,
        Query(alias="hub.challenge", min_length=1, max_length=500),
    ],
) -> PlainTextResponse:
    settings: Settings = request.app.state.settings
    configured_token = settings.meta_webhook_verify_token.get_secret_value()
    valid_token = hmac.compare_digest(
        verify_token.encode("utf-8"),
        configured_token.encode("utf-8"),
    )
    if mode != "subscribe" or not valid_token:
        raise WebhookVerificationDenied
    return PlainTextResponse(challenge)


@router.post("", response_model=WebhookAck)
async def receive_webhook(
    request: Request,
    processor: WebhookProcessorDependency,
    signature: Annotated[
        str | None,
        Header(alias="X-Hub-Signature-256"),
    ] = None,
) -> WebhookProcessingResult:
    if signature is None:
        raise InvalidWebhookSignature
    raw_body = await request.body()
    return await processor.process(
        raw_body=raw_body,
        signature=signature,
        correlation_id=request.state.correlation_id,
    )
