"""Immutable receipt-time admission, independent of delayed conversation workers."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.account_lifecycle import lock_account_lifecycle
from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.channel_binding import (
    AccountAgentBindingRepository,
)
from .repository import AgentOperationRepository


class MessageAdmission(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant_id: UUID
    source_event_id: UUID
    whatsapp_account_id: UUID
    agent_instance_id: UUID | None
    operation_revision: int | None
    binding_revision: int | None
    eligible: bool
    reason: str
    admitted_at: datetime


async def admit_event(
    session: AsyncSession,
    context: TenantContext,
    *,
    event_id: UUID,
    account_id: UUID,
    provider_timestamp: datetime | None,
) -> MessageAdmission:
    await set_tenant_context(session, context.tenant_id)
    await lock_account_lifecycle(session, context.tenant_id, account_id)
    existing = (
        (
            await session.execute(
                text(
                    "SELECT * FROM public.agent_message_admissions WHERE tenant_id=:t AND source_event_id=:e"
                ),
                {"t": context.tenant_id, "e": event_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        return MessageAdmission.model_validate(dict(existing))
    source_account = await session.scalar(
        text(
            "SELECT whatsapp_account_id FROM public.whatsapp_webhook_events WHERE tenant_id=:t AND id=:e"
        ),
        {"t": context.tenant_id, "e": event_id},
    )
    if source_account != account_id:
        raise ValueError("admission source/account mismatch")
    binding = await AccountAgentBindingRepository(session, context).get_for_account(
        account_id
    )
    agent_id = None if binding is None else binding.agent_instance_id
    state = None
    reason = "unassigned"
    if agent_id is not None:
        repository = AgentOperationRepository(session, context)
        await repository.lock(agent_id)
        state = await repository.get(agent_id)
        if state is None:
            reason = "operation_unavailable"
        elif not state.enabled:
            reason = "paused"
        elif provider_timestamp is None or provider_timestamp.tzinfo is None:
            reason = "invalid_timestamp"
        elif state.resumed_at is not None and provider_timestamp <= state.resumed_at:
            reason = "before_resume"
        else:
            reason = "eligible"
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO public.agent_message_admissions "
                    "(tenant_id,source_event_id,whatsapp_account_id,agent_instance_id,operation_revision,binding_revision,eligible,reason) "
                    "VALUES(:t,:e,:a,:agent,:revision,:binding,:eligible,:reason) RETURNING *"
                ),
                {
                    "t": context.tenant_id,
                    "e": event_id,
                    "a": account_id,
                    "agent": agent_id,
                    "revision": None if state is None else state.revision,
                    "binding": None if binding is None else binding.revision,
                    "eligible": reason == "eligible",
                    "reason": reason,
                },
            )
        )
        .mappings()
        .one()
    )
    admission = MessageAdmission.model_validate(dict(row))
    if not admission.eligible:
        from agents_factory.common.audit import AuditService

        await AuditService(session).record(
            context=context,
            event_type="agent.message.not_admitted",
            entity_type="whatsapp_event",
            entity_id=event_id,
            payload={"reason": reason},
        )
    return admission


async def check_message_eligibility(
    session: AsyncSession, context: TenantContext, *, message_id: UUID
) -> bool:
    await set_tenant_context(session, context.tenant_id)
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM public.messages m "
                "JOIN public.agent_message_admissions adm ON (adm.tenant_id,adm.source_event_id)=(m.tenant_id,m.source_event_id) "
                "JOIN public.agent_operation_states state ON (state.tenant_id,state.agent_instance_id)=(adm.tenant_id,adm.agent_instance_id) "
                "JOIN public.account_agent_bindings binding ON (binding.tenant_id,binding.whatsapp_account_id)=(adm.tenant_id,adm.whatsapp_account_id) "
                "JOIN public.conversations c ON (c.tenant_id,c.id)=(m.tenant_id,m.conversation_id) "
                "WHERE m.tenant_id=:t AND m.id=:m AND m.direction='inbound' AND m.sender_type='customer' "
                "AND c.whatsapp_account_id=adm.whatsapp_account_id AND adm.eligible AND state.enabled "
                "AND state.revision=adm.operation_revision AND binding.agent_instance_id=adm.agent_instance_id "
                "AND binding.revision=adm.binding_revision)"
            ),
            {"t": context.tenant_id, "m": message_id},
        )
    )
