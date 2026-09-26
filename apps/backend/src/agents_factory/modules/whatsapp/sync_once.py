"""One-shot WhatsApp Business app synchronization coordination."""

from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context

SyncType = Literal["smb_app_state_sync", "history"]
SyncState = Literal["UNKNOWN", "ACCEPTED"]
SyncSender = Callable[[str, SyncType], Awaitable[str]]


async def request_sync_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    account_id: UUID,
    sync_type: SyncType,
    send: SyncSender,
) -> SyncState:
    """Reserve before any HTTP call; never auto-repeat an uncertain request."""
    if sync_type not in {"smb_app_state_sync", "history"}:
        raise ValueError("Invalid sync type")
    async with session_factory.begin() as session:
        await set_tenant_context(session, tenant_id)
        account = (
            (
                await session.execute(
                    text(
                        "SELECT phone_number_id,verified_at FROM public.whatsapp_accounts "
                        "WHERE tenant_id=:tenant AND id=:account AND status='active' "
                        "AND mode='COEXISTENCE' AND coexistence_eligibility='ELIGIBLE'"
                    ),
                    {"tenant": tenant_id, "account": account_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if account is None:
            raise ValueError("Active eligible coexistence account required")
        reserved = (
            await session.scalar(
                text(
                    "INSERT INTO public.whatsapp_sync_requests "
                    "(id,tenant_id,whatsapp_account_id,sync_type,state) "
                    "SELECT :id,:tenant,:account,:sync_type,'UNKNOWN' "
                    "WHERE :verified_at >= now() - interval '24 hours' "
                    "ON CONFLICT (tenant_id,whatsapp_account_id,sync_type) DO NOTHING RETURNING id"
                ),
                {
                    "id": new_uuid7(),
                    "tenant": tenant_id,
                    "account": account_id,
                    "sync_type": sync_type,
                    "verified_at": account["verified_at"],
                },
            )
            if account["verified_at"] is not None
            else None
        )
        if reserved is None:
            existing = await session.scalar(
                text(
                    "SELECT state FROM public.whatsapp_sync_requests "
                    "WHERE tenant_id=:tenant AND whatsapp_account_id=:account AND sync_type=:sync_type"
                ),
                {"tenant": tenant_id, "account": account_id, "sync_type": sync_type},
            )
            if existing is None:
                raise ValueError("Meta sync window has expired")
            return existing
        phone_number_id = account["phone_number_id"]
    # This transaction has committed. A crash or timeout can no longer cause a
    # second worker to repeat Meta's one-time endpoint.
    try:
        request_id = await send(phone_number_id, sync_type)
        if not isinstance(request_id, str) or not request_id:
            return "UNKNOWN"
    except Exception:
        return "UNKNOWN"
    async with session_factory.begin() as session:
        await set_tenant_context(session, tenant_id)
        updated = await session.scalar(
            text(
                "UPDATE public.whatsapp_sync_requests SET state='ACCEPTED', "
                "request_id=:request_id,updated_at=now() "
                "WHERE tenant_id=:tenant AND whatsapp_account_id=:account "
                "AND sync_type=:sync_type AND state='UNKNOWN' RETURNING id"
            ),
            {
                "tenant": tenant_id,
                "account": account_id,
                "sync_type": sync_type,
                "request_id": request_id,
            },
        )
        if updated is None:
            return "UNKNOWN"
    return "ACCEPTED"
