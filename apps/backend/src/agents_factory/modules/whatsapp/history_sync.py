import hashlib
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.contracts import WhatsAppHistorySync
from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping


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
