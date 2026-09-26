import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.contracts import WhatsAppHistorySync
from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping
from agents_factory.modules.whatsapp.schemas import (
    MetaHistoryChunk,
    MetaHistoryFailure,
    MetaInboundMessage,
)


class HistoryInboxPayload(BaseModel):
    chunks: list[MetaHistoryChunk | MetaHistoryFailure]
    media_messages: list[MetaInboundMessage]


@dataclass(frozen=True, slots=True)
class HistoricalMessage:
    provider_id: str
    customer_wa_id: str
    direction: Literal["inbound", "outbound"]
    occurred_at: datetime
    content: dict[str, object] = field(repr=False)


@dataclass(frozen=True, slots=True)
class HistoryProjection:
    messages: tuple[HistoricalMessage, ...] = field(repr=False)
    media_updates: tuple[dict[str, object], ...] = field(repr=False)
    progress: tuple[tuple[int, int, int], ...]
    errors: tuple[dict[str, object], ...] = field(repr=False)


def project_history(payload: object) -> HistoryProjection:
    """Project a validated archive, never the live conversation or AI pipeline.

    Meta thread IDs identify the customer; senders differing from that ID are
    business messages. Standalone media cannot identify an outbound recipient,
    so keep it for matching against the original archived message by provider ID.
    """
    parsed = HistoryInboxPayload.model_validate(payload)
    messages: dict[str, HistoricalMessage] = {}
    progress: set[tuple[int, int, int]] = set()
    errors: list[dict[str, object]] = []
    for chunk in parsed.chunks:
        if isinstance(chunk, MetaHistoryFailure):
            errors.extend(
                error.model_dump(exclude_unset=True) for error in chunk.errors
            )
            continue
        progress.add(
            (chunk.metadata.phase, chunk.metadata.chunk_order, chunk.metadata.progress)
        )
        for thread in chunk.threads:
            for message in thread.messages:
                historical = HistoricalMessage(
                    provider_id=message.id,
                    customer_wa_id=thread.id,
                    direction="inbound"
                    if message.sender_wa_id == thread.id
                    else "outbound",
                    occurred_at=datetime.fromtimestamp(int(message.timestamp), tz=UTC),
                    content=message.model_dump(by_alias=True, exclude_unset=True),
                )
                previous = messages.get(message.id)
                if previous is not None and previous != historical:
                    raise ValueError("Conflicting historical message")
                messages[message.id] = historical
    return HistoryProjection(
        messages=tuple(
            sorted(
                messages.values(), key=lambda item: (item.occurred_at, item.provider_id)
            )
        ),
        media_updates=tuple(
            message.model_dump(by_alias=True, exclude_unset=True)
            for message in parsed.media_messages
        ),
        progress=tuple(sorted(progress)),
        errors=tuple(errors),
    )


async def import_history_inbox(
    session: AsyncSession,
    *,
    context: TenantContext,
    inbox_id: UUID,
) -> int:
    """Import one stored batch into an archive, never a live conversation."""
    await set_tenant_context(session, context.tenant_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT inbox.whatsapp_account_id, inbox.payload "
                    "FROM public.whatsapp_history_inbox AS inbox "
                    "JOIN public.whatsapp_accounts AS account "
                    "ON account.tenant_id=inbox.tenant_id AND account.id=inbox.whatsapp_account_id "
                    "WHERE inbox.tenant_id=:tenant AND inbox.id=:inbox "
                    "AND account.status='active' AND account.mode='COEXISTENCE'"
                ),
                {"tenant": context.tenant_id, "inbox": inbox_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("History inbox not found for active coexistence account")
    projection = project_history(row["payload"])
    if projection.media_updates:
        raise ValueError(
            "Historical media updates require reconciliation before import"
        )
    if projection.errors and projection.messages:
        raise ValueError("Mixed history denial and message content")
    async with session.begin_nested():
        claimed = await session.scalar(
            text(
                "INSERT INTO public.whatsapp_history_import_receipts "
                "(id,tenant_id,whatsapp_account_id,inbox_id,outcome,progress,errors) "
                "VALUES (:id,:tenant,:account,:inbox,:outcome,CAST(:progress AS jsonb),CAST(:errors AS jsonb)) "
                "ON CONFLICT (tenant_id,inbox_id) DO NOTHING RETURNING id"
            ),
            {
                "id": new_uuid7(),
                "tenant": context.tenant_id,
                "account": row["whatsapp_account_id"],
                "inbox": inbox_id,
                "outcome": "DECLINED" if projection.errors else "IMPORTED",
                "progress": json.dumps(projection.progress),
                "errors": json.dumps(projection.errors),
            },
        )
        if claimed is None:
            return 0
        imported = 0
        for message in projection.messages:
            content = json.dumps(message.content, ensure_ascii=False, sort_keys=True)
            inserted = await session.scalar(
                text(
                    "INSERT INTO public.whatsapp_history_messages "
                    "(id,tenant_id,whatsapp_account_id,provider_message_id,customer_wa_id,"
                    "direction,content,provider_timestamp) "
                    "VALUES (:id,:tenant,:account,:provider,:customer,:direction,"
                    "CAST(:content AS jsonb),:occurred_at) "
                    "ON CONFLICT (tenant_id,whatsapp_account_id,provider_message_id) "
                    "DO NOTHING RETURNING id"
                ),
                {
                    "id": new_uuid7(),
                    "tenant": context.tenant_id,
                    "account": row["whatsapp_account_id"],
                    "provider": message.provider_id,
                    "customer": message.customer_wa_id,
                    "direction": message.direction,
                    "content": content,
                    "occurred_at": message.occurred_at,
                },
            )
            if inserted is not None:
                imported += 1
                continue
            existing = (
                (
                    await session.execute(
                        text(
                            "SELECT customer_wa_id,direction,content,provider_timestamp "
                            "FROM public.whatsapp_history_messages WHERE tenant_id=:tenant "
                            "AND whatsapp_account_id=:account AND provider_message_id=:provider"
                        ),
                        {
                            "tenant": context.tenant_id,
                            "account": row["whatsapp_account_id"],
                            "provider": message.provider_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            if (
                existing["customer_wa_id"] != message.customer_wa_id
                or existing["direction"] != message.direction
                or existing["content"] != message.content
                or existing["provider_timestamp"] != message.occurred_at
            ):
                raise ValueError("Conflicting historical message")
        return imported


async def persist_history(
    session: AsyncSession,
    *,
    context: TenantContext,
    mapping: WhatsAppAccountMapping,
    event: WhatsAppHistorySync,
) -> bool:
    """Durably accept history without running the live-message pipeline."""
    await set_tenant_context(session, context.tenant_id)
    account = await session.scalar(
        text(
            "SELECT id FROM public.whatsapp_accounts WHERE tenant_id=:tenant "
            "AND id=:account AND waba_id=:waba AND phone_number_id=:phone "
            "AND status='active' AND mode='COEXISTENCE'"
        ),
        {
            "tenant": context.tenant_id,
            "account": mapping.account_id,
            "waba": event.waba_id,
            "phone": event.phone_number_id,
        },
    )
    if account is None or context.tenant_id != mapping.tenant_id:
        raise DomainError(
            type="https://agents-factory.dev/problems/history-sync-account",
            title="Invalid history sync account",
            status=409,
            detail="An active coexistence account is required.",
            code="history_sync_account_invalid",
        )
    payload = json.dumps(
        {"chunks": event.chunks, "media_messages": event.media_messages},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    inserted = await session.scalar(
        text(
            "INSERT INTO public.whatsapp_history_inbox "
            "(id,tenant_id,whatsapp_account_id,payload_digest,payload) "
            "VALUES (:id,:tenant,:account,:digest,CAST(:payload AS jsonb)) "
            "ON CONFLICT (tenant_id,whatsapp_account_id,payload_digest) DO NOTHING RETURNING id"
        ),
        {
            "id": new_uuid7(),
            "tenant": context.tenant_id,
            "account": mapping.account_id,
            "digest": hashlib.sha256(payload.encode()).hexdigest(),
            "payload": payload,
        },
    )
    return inserted is not None
