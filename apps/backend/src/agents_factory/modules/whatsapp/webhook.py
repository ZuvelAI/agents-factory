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
from agents_factory.modules.whatsapp.outbound_service import (
    OutboundStatusReconciler,
    lock_conversation_dispatch,
)
from agents_factory.modules.whatsapp.repository import WhatsAppWebhookRepository
from agents_factory.modules.whatsapp.mobile_echo import ingest_mobile_echo
from agents_factory.modules.whatsapp.contact_sync import ingest_contact_change
from agents_factory.modules.whatsapp.history_sync import persist_history


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


class UnprocessedAccountUpdate(DomainError):
    def __init__(self) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/unprocessed-account-update",
            title="Unprocessed Account Update",
            status=503,
            detail="The Meta account update could not be matched safely.",
            code="unprocessed_account_update",
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
        self._session = session
        self._outbox = OutboxService(session)
        self._outbound_status = OutboundStatusReconciler(session)
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
        # Acquire every affected conversation fence before any row lock. Sorting
        # only echoes is insufficient for batches mixing echoes and statuses.
        targets: set[tuple[str, str, str]] = set()
        targets.update(
            (echo.waba_id, echo.phone_number_id, echo.recipient_wa_id)
            for echo in batch.mobile_echoes
        )
        targets.update(
            (status.waba_id, status.phone_number_id, status.recipient_wa_id)
            for status in batch.delivery_statuses
        )
        targets.update(
            (inbound.waba_id, inbound.phone_number_id, inbound.sender_wa_id)
            for inbound in batch.inbound_events
        )
        targets.update(
            (contact.waba_id, contact.phone_number_id, contact.customer_wa_id)
            for contact in batch.contact_changes
        )
        for waba_id, phone_number_id, customer_wa_id in sorted(targets):
            mapping = await self._repository.resolve_active_mapping(
                waba_id=waba_id,
                phone_number_id=phone_number_id,
            )
            if mapping is None:
                raise UnknownAccountMapping
            await lock_conversation_dispatch(
                self._session,
                tenant_id=mapping.tenant_id,
                account_id=mapping.account_id,
                customer_wa_id=customer_wa_id,
            )
        # A batch can span multiple accounts/agents. Acquire authority fences in
        # stable global order before persisting any event, never worker-time.
        from agents_factory.common.account_lifecycle import lock_account_lifecycle
        from agents_factory.modules.agent_operations.repository import (
            AgentOperationRepository,
        )
        from agents_factory.modules.agent_factory.channel_binding import (
            AccountAgentBindingRepository,
        )

        authority_accounts: set[tuple[UUID, UUID]] = set()
        for inbound in batch.inbound_events:
            mapping = await self._repository.resolve_active_mapping(
                waba_id=inbound.waba_id, phone_number_id=inbound.phone_number_id
            )
            if mapping is not None:
                authority_accounts.add((mapping.tenant_id, mapping.account_id))
        for tenant, account in sorted(authority_accounts):
            await lock_account_lifecycle(self._session, tenant, account)
        authority_agents: set[tuple[UUID, UUID]] = set()
        for tenant, account in sorted(authority_accounts):
            authority_context = TenantContext(tenant, None, "system", correlation_id)
            binding = await AccountAgentBindingRepository(
                self._session, authority_context
            ).get_for_account(account)
            if binding is not None:
                authority_agents.add((tenant, binding.agent_instance_id))
        for tenant, agent in sorted(authority_agents):
            await AgentOperationRepository(
                self._session, TenantContext(tenant, None, "system", correlation_id)
            ).lock(agent)
        accepted_messages = 0
        duplicate_messages = 0
        for history_event in batch.history_sync:
            mapping = await self._repository.resolve_active_mapping(
                waba_id=history_event.waba_id,
                phone_number_id=history_event.phone_number_id,
            )
            if mapping is None:
                raise UnknownAccountMapping
            context = TenantContext(
                tenant_id=mapping.tenant_id,
                actor_id=None,
                actor_type="system",
                correlation_id=correlation_id,
            )
            inbox_id = await persist_history(
                self._session, context=context, mapping=mapping, event=history_event
            )
            if inbox_id is not None:
                await self._outbox.enqueue(
                    context=context,
                    idempotency_key=f"whatsapp.history.import:{inbox_id}",
                    topic="whatsapp.history.import",
                    payload={
                        "aggregate_id": str(inbox_id),
                        "inbox_id": str(inbox_id),
                        "whatsapp_account_id": str(mapping.account_id),
                    },
                )
        for contact_event in batch.contact_changes:
            mapping = await self._repository.resolve_active_mapping(
                waba_id=contact_event.waba_id,
                phone_number_id=contact_event.phone_number_id,
            )
            if mapping is None:
                raise UnknownAccountMapping
            context = TenantContext(
                tenant_id=mapping.tenant_id,
                actor_id=None,
                actor_type="system",
                correlation_id=correlation_id,
            )
            await ingest_contact_change(
                self._session, context=context, mapping=mapping, event=contact_event
            )
        # Apply human control before any customer messages in the same batch.
        for echo_event in batch.mobile_echoes:
            mapping = await self._repository.resolve_active_mapping(
                waba_id=echo_event.waba_id,
                phone_number_id=echo_event.phone_number_id,
            )
            if mapping is None:
                raise UnknownAccountMapping
            context = TenantContext(
                tenant_id=mapping.tenant_id,
                actor_id=None,
                actor_type="system",
                correlation_id=correlation_id,
            )
            created = await ingest_mobile_echo(
                self._session, context=context, mapping=mapping, event=echo_event
            )
            if created:
                accepted_messages += 1
            else:
                duplicate_messages += 1
        for inbound_event in batch.inbound_events:
            mapping = await self._repository.resolve_active_mapping(
                waba_id=inbound_event.waba_id,
                phone_number_id=inbound_event.phone_number_id,
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
                event=inbound_event,
            )
            if not persisted.created:
                duplicate_messages += 1
                continue
            from agents_factory.modules.agent_operations.admission import admit_event

            await admit_event(
                self._session,
                context,
                event_id=persisted.event_id,
                account_id=mapping.account_id,
                provider_timestamp=inbound_event.occurred_at,
            )
            await self._outbox.enqueue(
                context=context,
                idempotency_key=f"whatsapp.inbound:{inbound_event.whatsapp_message_id}",
                topic="whatsapp.inbound.received",
                payload={
                    "aggregate_id": str(persisted.event_id),
                    "event_id": str(persisted.event_id),
                    "whatsapp_account_id": str(mapping.account_id),
                    "whatsapp_message_id": inbound_event.whatsapp_message_id,
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
            context = TenantContext(
                tenant_id=mapping.tenant_id,
                actor_id=None,
                actor_type="system",
                correlation_id=correlation_id,
            )
            await self._outbound_status.reconcile(
                context=context,
                whatsapp_account_id=mapping.account_id,
                event=status,
            )

        for update in batch.account_updates:
            if update.event != "PARTNER_REMOVED" or update.display_phone_digits is None:
                await self._repository.queue_account_update_alert(
                    waba_id=update.waba_id,
                    event=update.event,
                    display_phone_digits=update.display_phone_digits,
                    occurred_at=update.occurred_at,
                    reason="unsupported_event",
                )
                continue
            result = await self._repository.apply_partner_removed(
                waba_id=update.waba_id,
                display_phone_digits=update.display_phone_digits,
                occurred_at=update.occurred_at,
            )
            if result in {"unmatched", "unverified"}:
                await self._repository.queue_account_update_alert(
                    waba_id=update.waba_id,
                    event=update.event,
                    display_phone_digits=update.display_phone_digits,
                    occurred_at=update.occurred_at,
                    reason=result,
                )
            elif result not in {"deactivated", "already_inactive", "stale"}:
                raise UnprocessedAccountUpdate

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
