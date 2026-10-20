"""Explicit role fixture for audio; no provider calls or personal media."""

from uuid import uuid4
from sqlalchemy import text

AUDIO_TABLES = ("public.whatsapp_audio_transcriptions",)


async def seed_audio_table(connection, tenant, rows):
    identity = uuid4()
    rows[AUDIO_TABLES[0]] = identity
    await connection.execute(
        text(
            "INSERT INTO public.whatsapp_audio_transcriptions "
            "(id,tenant_id,inbound_message_id,conversation_id,whatsapp_account_id,source_event_id,media_id,mime_type) "
            "VALUES(:id,:tenant,:message,:conversation,:account,:event,'12345678','audio/ogg')"
        ),
        {
            "id": identity,
            "tenant": tenant,
            "message": rows["public.messages"],
            "conversation": rows["public.conversations"],
            "account": rows["public.whatsapp_accounts"],
            "event": rows["public.whatsapp_webhook_events"],
        },
    )
