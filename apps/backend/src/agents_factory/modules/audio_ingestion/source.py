"""Derive audio identity only from a persisted provider-origin message."""

import base64
import binascii
import re
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.schemas import MetaChangeValue, MetaWebhookPayload
from .models import AudioSource


async def load_audio_source(
    session: AsyncSession, context: TenantContext, message_id: UUID
) -> AudioSource:
    await set_tenant_context(session, context.tenant_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT m.id,m.source_event_id,m.conversation_id,m.arrival_sequence,"
                    "c.whatsapp_account_id,c.customer_wa_id,e.raw_payload,e.whatsapp_message_id,"
                    "a.waba_id,a.phone_number_id FROM public.messages m "
                    "JOIN public.conversations c ON (c.tenant_id,c.id)=(m.tenant_id,m.conversation_id) "
                    "JOIN public.whatsapp_webhook_events e ON e.tenant_id=m.tenant_id AND e.id=m.source_event_id "
                    "AND e.whatsapp_account_id=c.whatsapp_account_id AND e.sender_wa_id=c.customer_wa_id "
                    "JOIN public.whatsapp_accounts a ON (a.tenant_id,a.id)=(c.tenant_id,c.whatsapp_account_id) "
                    "WHERE m.tenant_id=:tenant AND m.id=:id AND m.direction='inbound' "
                    "AND m.sender_type='customer' AND m.message_type='audio' AND e.message_type='audio'"
                ),
                {"tenant": context.tenant_id, "id": message_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("audio_source_unavailable")
    try:
        payload = MetaWebhookPayload.model_validate(row["raw_payload"])
    except ValidationError:
        raise ValueError("audio_source_invalid") from None
    matched = []
    for entry in payload.entry:
        if entry.id != row["waba_id"]:
            continue
        for change in entry.changes:
            if change.field != "messages" or not isinstance(
                change.value, MetaChangeValue
            ):
                continue
            if change.value.metadata.phone_number_id != row["phone_number_id"]:
                continue
            for message in change.value.messages:
                if (
                    message.id == row["whatsapp_message_id"]
                    and message.sender_wa_id == row["customer_wa_id"]
                    and message.type == "audio"
                ):
                    matched.append((message.model_extra or {}).get("audio"))
    if len(matched) != 1 or not isinstance(matched[0], dict):
        raise ValueError("audio_source_invalid")
    audio = matched[0]
    media_id, mime = audio.get("id"), audio.get("mime_type")
    if not isinstance(media_id, str) or re.fullmatch(r"[0-9]{1,200}", media_id) is None:
        raise ValueError("audio_media_id_invalid")
    if not isinstance(mime, str) or not 1 <= len(mime) <= 100:
        raise ValueError("audio_mime_invalid")
    expected = None
    if audio.get("sha256") is not None:
        try:
            value = audio["sha256"]
            if not isinstance(value, str):
                raise ValueError
            decoded = base64.b64decode(value, validate=True)
            if len(decoded) != 32:
                raise ValueError
            expected = decoded.hex()
        except (ValueError, binascii.Error):
            raise ValueError("audio_hash_invalid") from None
    return AudioSource(
        context.tenant_id,
        row["whatsapp_account_id"],
        row["conversation_id"],
        message_id,
        row["source_event_id"],
        row["whatsapp_message_id"],
        media_id,
        mime,
        expected,
        row["arrival_sequence"],
    )
