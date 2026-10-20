"""Synthetic signed-event-shaped fixtures. No network or real recordings."""

import base64
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from apps.backend.tests.integration.test_lead_capture import seed, inbound


async def audio_world(factory, *, tenant=None, media_id="12345678"):
    world = await seed(factory, tenant=tenant)
    message = await audio_message(factory, world, media_id=media_id)
    return world, message


async def audio_message(factory, world, *, media_id="12345678", sequence=1):
    message, _ = await inbound(factory, world, "fixture", sequence=sequence)
    async with factory.begin() as session:
        event = (
            await session.execute(
                text("SELECT source_event_id FROM public.messages WHERE id=:id"),
                {"id": message},
            )
        ).scalar_one()
        raw = await session.scalar(
            text("SELECT raw_payload FROM public.whatsapp_webhook_events WHERE id=:id"),
            {"id": event},
        )
        item = raw["entry"][0]["changes"][0]["value"]["messages"][0]
        item.pop("text")
        item.update(
            type="audio",
            audio={
                "id": media_id,
                "mime_type": "audio/ogg; codecs=opus",
                "sha256": base64.b64encode(b"x" * 32).decode(),
                "voice": True,
            },
        )
        await session.execute(
            text(
                "UPDATE public.whatsapp_webhook_events SET message_type='audio',normalized_content='{}',raw_payload=:raw WHERE id=:id"
            ).bindparams(bindparam("raw", type_=JSONB)),
            {"id": event, "raw": raw},
        )
        await session.execute(
            text(
                "UPDATE public.messages SET message_type='audio',content='{}' WHERE id=:id"
            ),
            {"id": message},
        )
    return message
