"""Session fences on the dispatch connection; no transaction spans provider HTTP."""

from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.common.account_lifecycle import account_lifecycle_key
from agents_factory.common.context import TenantContext
from .admission import check_message_eligibility
from .repository import operation_lock_key


async def acquire_delivery_fences(
    session: AsyncSession, context: TenantContext, *, outbound_id: UUID
) -> tuple[str, ...]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT o.whatsapp_account_id,adm.agent_instance_id FROM public.outbound_messages o "
                    "LEFT JOIN public.messages source ON (source.tenant_id,source.id)=(o.tenant_id,o.source_message_id) "
                    "LEFT JOIN public.messages incoming ON (incoming.tenant_id,incoming.id)=(source.tenant_id,source.in_reply_to_message_id) "
                    "LEFT JOIN public.agent_message_admissions adm ON (adm.tenant_id,adm.source_event_id)=(incoming.tenant_id,incoming.source_event_id) "
                    "WHERE o.tenant_id=:t AND o.id=:o"
                ),
                {"t": context.tenant_id, "o": outbound_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return ()
    keys = [account_lifecycle_key(context.tenant_id, row["whatsapp_account_id"])]
    if row["agent_instance_id"] is not None:
        keys.append(operation_lock_key(context.tenant_id, row["agent_instance_id"]))
    for key in keys:
        await session.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:key,0))"), {"key": key}
        )
    return tuple(keys)


async def outbound_operation_allowed(
    session: AsyncSession, context: TenantContext, *, outbound_id: UUID
) -> bool:
    row = (
        (
            await session.execute(
                text(
                    "SELECT o.kind,source.sender_type,source.in_reply_to_message_id, "
                    "EXISTS(SELECT 1 FROM public.audit_events audit WHERE audit.tenant_id=o.tenant_id "
                    "AND audit.entity_id=o.id AND audit.entity_type='outbound_message' "
                    "AND audit.event_type='whatsapp.template_send.prepared' "
                    "AND audit.actor_type='platform_admin' AND audit.actor_id IS NOT NULL) AS manual_template "
                    "FROM public.outbound_messages o LEFT JOIN public.messages source "
                    "ON (source.tenant_id,source.id)=(o.tenant_id,o.source_message_id) "
                    "WHERE o.tenant_id=:t AND o.id=:o"
                ),
                {"t": context.tenant_id, "o": outbound_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return False
    if row["sender_type"] == "human":
        return True
    if row["sender_type"] == "ai" and isinstance(row["in_reply_to_message_id"], UUID):
        return await check_message_eligibility(
            session, context, message_id=row["in_reply_to_message_id"]
        )
    # A proactive manual template is not an agent response. Never infer that
    # privilege from the current worker's system context or template approval.
    return row["kind"] == "template" and row["manual_template"] is True
