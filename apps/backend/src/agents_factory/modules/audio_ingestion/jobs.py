"""Load durable IDs, never accept media URLs or identity from an envelope."""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.queue import JobEnvelope, InvalidJobEnvelope
from agents_factory.database import set_tenant_context


async def load_message_id(session: AsyncSession, envelope: JobEnvelope) -> UUID:
    await set_tenant_context(session, envelope.tenant_id)
    value = await session.scalar(
        text(
            "SELECT payload FROM public.outbox_jobs WHERE tenant_id=:t AND id=:j AND topic=:kind"
        ),
        {"t": envelope.tenant_id, "j": envelope.job_id, "kind": envelope.kind},
    )
    if (
        not isinstance(value, Mapping)
        or value.get("aggregate_id") != str(envelope.aggregate_id)
        or value.get("conversation_id") != str(envelope.aggregate_id)
    ):
        raise InvalidJobEnvelope("audio_job_scope_invalid")
    try:
        message = UUID(str(value["inbound_message_id"]))
    except (KeyError, ValueError, TypeError):
        raise InvalidJobEnvelope("audio_job_message_invalid") from None
    exists = await session.scalar(
        text(
            "SELECT id FROM public.messages WHERE tenant_id=:t AND id=:m AND conversation_id=:c AND direction='inbound' AND sender_type='customer'"
        ),
        {"t": envelope.tenant_id, "m": message, "c": envelope.aggregate_id},
    )
    if exists != message:
        raise InvalidJobEnvelope("audio_job_message_scope_invalid")
    return message
