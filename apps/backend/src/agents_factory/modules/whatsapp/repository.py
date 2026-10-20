from __future__ import annotations

from .contact_profile_repository import persist_contact_profile

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.contracts import InboundWhatsAppEvent


@dataclass(frozen=True, slots=True)
class WhatsAppAccountMapping:
    account_id: UUID
    tenant_id: UUID


@dataclass(frozen=True, slots=True)
class PersistedWebhookEvent:
    event_id: UUID
    created: bool


class WhatsAppWebhookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def queue_account_update_alert(
        self,
        *,
        waba_id: str,
        event: str,
        display_phone_digits: str | None,
        occurred_at: datetime,
        reason: str,
    ) -> None:
        fingerprint = hashlib.sha256(
            json.dumps(
                [waba_id, event, display_phone_digits, occurred_at.isoformat()],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        await self._session.execute(
            text(
                "INSERT INTO agents_factory_private.whatsapp_account_update_alerts "
                "(id, event_fingerprint, waba_id, event, display_phone_digits, "
                "occurred_at, reason) VALUES "
                "(:id, :fingerprint, :waba_id, :event, :display_phone_digits, "
                ":occurred_at, :reason) ON CONFLICT DO NOTHING"
            ),
            {
                "id": new_uuid7(),
                "fingerprint": fingerprint,
                "waba_id": waba_id,
                "event": event,
                "display_phone_digits": display_phone_digits,
                "occurred_at": occurred_at,
                "reason": reason,
            },
        )

    async def apply_partner_removed(
        self,
        *,
        waba_id: str,
        display_phone_digits: str,
        occurred_at: datetime,
    ) -> str:
        tenant_id = await self._session.scalar(
            text(
                "SELECT agents_factory_private.resolve_whatsapp_update_tenant("
                ":waba_id, :display_phone_digits)"
            ),
            {"waba_id": waba_id, "display_phone_digits": display_phone_digits},
        )
        if not isinstance(tenant_id, UUID):
            return "unmatched"
        await set_tenant_context(self._session, tenant_id)
        from agents_factory.common.account_lifecycle import lock_account_lifecycle

        account_ids = (
            (
                await self._session.execute(
                    text(
                        "SELECT id FROM public.whatsapp_accounts WHERE tenant_id=:tenant AND waba_id=:waba AND display_phone_digits=:digits ORDER BY id"
                    ),
                    {
                        "tenant": tenant_id,
                        "waba": waba_id,
                        "digits": display_phone_digits,
                    },
                )
            )
            .scalars()
            .all()
        )
        for account_id in account_ids:
            await lock_account_lifecycle(self._session, tenant_id, account_id)
        result = await self._session.scalar(
            text(
                "SELECT agents_factory_private.apply_whatsapp_partner_removed("
                ":waba_id, :display_phone_digits, :occurred_at)"
            ),
            {
                "waba_id": waba_id,
                "display_phone_digits": display_phone_digits,
                "occurred_at": occurred_at,
            },
        )
        if not isinstance(result, str):
            raise RuntimeError("Meta disconnect result is unavailable")
        return result

    async def resolve_active_mapping(
        self,
        *,
        waba_id: str,
        phone_number_id: str,
    ) -> WhatsAppAccountMapping | None:
        result = await self._session.execute(
            text(
                "SELECT account_id, tenant_id FROM "
                "agents_factory_private.resolve_active_whatsapp_account("
                ":waba_id, :phone_number_id)"
            ),
            {"waba_id": waba_id, "phone_number_id": phone_number_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return WhatsAppAccountMapping(
            account_id=row["account_id"],
            tenant_id=row["tenant_id"],
        )

    async def persist_inbound(
        self,
        *,
        context: TenantContext,
        mapping: WhatsAppAccountMapping,
        event: InboundWhatsAppEvent,
    ) -> PersistedWebhookEvent:
        await set_tenant_context(self._session, context.tenant_id)
        event_id = new_uuid7()
        statement = text(
            "INSERT INTO public.whatsapp_webhook_events "
            "(id, tenant_id, whatsapp_account_id, whatsapp_message_id, "
            "sender_wa_id, message_type, normalized_content, "
            "provider_timestamp, raw_payload) "
            "VALUES (:id, :tenant_id, :account_id, :message_id, :sender_wa_id, "
            ":message_type, :normalized_content, :provider_timestamp, "
            ":raw_payload) "
            "ON CONFLICT (tenant_id, whatsapp_message_id) DO NOTHING "
            "RETURNING id"
        ).bindparams(
            bindparam("normalized_content", type_=JSONB),
            bindparam("raw_payload", type_=JSONB),
        )
        created_id = await self._session.scalar(
            statement,
            {
                "id": event_id,
                "tenant_id": context.tenant_id,
                "account_id": mapping.account_id,
                "message_id": event.whatsapp_message_id,
                "sender_wa_id": event.sender_wa_id,
                "message_type": event.message_type,
                "normalized_content": event.content,
                "provider_timestamp": event.occurred_at,
                "raw_payload": event.raw_payload,
            },
        )
        if created_id is not None:
            await persist_contact_profile(
                self._session, context=context, mapping=mapping, event=event
            )
            return PersistedWebhookEvent(event_id=created_id, created=True)

        existing_id = await self._session.scalar(
            text(
                "SELECT id FROM public.whatsapp_webhook_events "
                "WHERE tenant_id = :tenant_id "
                "AND whatsapp_message_id = :message_id"
            ),
            {
                "tenant_id": context.tenant_id,
                "message_id": event.whatsapp_message_id,
            },
        )
        if existing_id is None:
            raise RuntimeError("deduplicated webhook event is not visible")
        return PersistedWebhookEvent(event_id=existing_id, created=False)
