"""Reusable short-transaction authority checks for paid work and fallback."""

from datetime import UTC, datetime
from typing import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.runtime.contracts import AgentSpecSnapshot
from agents_factory.modules.runtime.turn_service import AgentSpecProvider

SpecProviderBuilder = Callable[[AsyncSession, TenantContext, UUID], AgentSpecProvider]


class AudioAuthority:
    def __init__(self, provider: SpecProviderBuilder) -> None:
        self.provider = provider

    async def load(
        self,
        session: AsyncSession,
        context: TenantContext,
        message_id: UUID,
        *,
        lock: bool = False,
        now: datetime | None = None,
    ) -> AgentSpecSnapshot | None:
        await set_tenant_context(session, context.tenant_id)
        from agents_factory.modules.agent_operations.admission import (
            check_message_eligibility,
        )
        from agents_factory.modules.agent_operations.runtime_guard import (
            lock_message_operation,
        )

        if lock:
            eligible = await lock_message_operation(
                session, context, message_id=message_id
            )
        else:
            eligible = await check_message_eligibility(
                session, context, message_id=message_id
            )
        if not eligible:
            return None
        row = (
            await session.execute(
                text(
                    "SELECT c.id FROM public.messages m JOIN public.conversations c ON (c.tenant_id,c.id)=(m.tenant_id,m.conversation_id) "
                    "JOIN public.whatsapp_accounts a ON (a.tenant_id,a.id)=(c.tenant_id,c.whatsapp_account_id) "
                    "WHERE m.tenant_id=:t AND m.id=:m AND m.direction='inbound' AND m.sender_type='customer' "
                    "AND c.control_state='AI_ACTIVE' AND a.status='active' "
                    "AND EXISTS(SELECT 1 FROM public.messages last_inbound WHERE last_inbound.tenant_id=c.tenant_id AND last_inbound.conversation_id=c.id "
                    "AND last_inbound.direction='inbound' AND last_inbound.sender_type='customer' AND last_inbound.provider_timestamp>=CAST(:now AS timestamptz)-interval '24 hours') "
                    "AND NOT EXISTS(SELECT 1 FROM public.messages h WHERE h.tenant_id=m.tenant_id AND h.conversation_id=m.conversation_id "
                    "AND h.sender_type='human' AND h.direction='outbound' AND (h.arrival_sequence>m.arrival_sequence OR h.provider_timestamp>=m.provider_timestamp)) "
                    + ("FOR UPDATE OF c" if lock else "")
                ),
                {
                    "t": context.tenant_id,
                    "m": message_id,
                    "now": now or datetime.now(UTC),
                },
            )
        ).one_or_none()
        if row is None:
            return None
        snapshot = await self.provider(session, context, row.id).get_active(
            tenant_id=context.tenant_id
        )
        if (
            snapshot is None
            or not snapshot.active
            or snapshot.tenant_id != context.tenant_id
        ):
            return None
        return snapshot
