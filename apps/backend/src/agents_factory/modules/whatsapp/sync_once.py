"""One-shot WhatsApp Business app synchronization coordination."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context

SyncType = Literal["smb_app_state_sync", "history"]
SyncState = Literal["UNKNOWN", "ACCEPTED"]
SyncSender = Callable[[str, SyncType], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class SyncStatus:
    sync_type: SyncType
    state: Literal["NOT_REQUESTED", "UNKNOWN", "ACCEPTED"]
    request_id: str | None
    reserved_at: datetime | None


async def get_sync_status(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
) -> tuple[SyncStatus, SyncStatus]:
    """Report request acceptance, not completion of Meta's async data delivery."""
    await set_tenant_context(session, tenant_id)
    exists = await session.scalar(
        text(
            "SELECT id FROM public.whatsapp_accounts WHERE tenant_id=:tenant "
            "AND id=:account AND mode='COEXISTENCE'"
        ),
        {"tenant": tenant_id, "account": account_id},
    )
    if exists is None:
        raise ValueError("Coexistence account not found")
    rows = (
        (
            await session.execute(
                text(
                    "SELECT sync_type,state,request_id,reserved_at "
                    "FROM public.whatsapp_sync_requests "
                    "WHERE tenant_id=:tenant AND whatsapp_account_id=:account"
                ),
                {"tenant": tenant_id, "account": account_id},
            )
        )
        .mappings()
        .all()
    )
    by_type = {row["sync_type"]: row for row in rows}

    def status_for(sync_type: SyncType) -> SyncStatus:
        row = by_type.get(sync_type)
        return SyncStatus(
            sync_type=sync_type,
            state=cast(
                Literal["NOT_REQUESTED", "UNKNOWN", "ACCEPTED"],
                row["state"] if row is not None else "NOT_REQUESTED",
            ),
            request_id=row["request_id"] if row is not None else None,
            reserved_at=row["reserved_at"] if row is not None else None,
        )

    return (
        status_for("smb_app_state_sync"),
        status_for("history"),
    )


async def enqueue_initial_sync(
    session: AsyncSession,
    *,
    context: TenantContext,
    account_id: UUID,
) -> None:
    """Schedule both one-shot sync kinds in the committed signup transaction."""
    await set_tenant_context(session, context.tenant_id)
    account = await session.scalar(
        text(
            "SELECT id FROM public.whatsapp_accounts WHERE tenant_id=:tenant "
            "AND id=:account AND status='active' AND mode='COEXISTENCE' "
            "AND coexistence_eligibility='ELIGIBLE' "
            "AND verified_at >= now() - interval '24 hours'"
        ),
        {"tenant": context.tenant_id, "account": account_id},
    )
    if account is None:
        raise ValueError(
            "Active eligible coexistence account required within sync window"
        )
    outbox = OutboxService(session)
    for sync_type in ("smb_app_state_sync", "history"):
        await outbox.enqueue(
            context=context,
            idempotency_key=f"whatsapp.sync.request:{account_id}:{sync_type}",
            topic="whatsapp.sync.request",
            payload={
                "aggregate_id": str(account_id),
                "whatsapp_account_id": str(account_id),
                "sync_type": sync_type,
            },
        )


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
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
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
            return cast(SyncState, existing)
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
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
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
