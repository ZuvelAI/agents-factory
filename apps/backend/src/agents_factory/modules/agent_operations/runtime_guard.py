"""Operational checks and short finalization fences shared by automatic turns."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.account_lifecycle import lock_account_lifecycle
from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.runtime.contracts import RuntimeTool, ToolInvocationContext
from agents_factory.modules.runtime.openai_adapter import AgentRuntimeError
from agents_factory.modules.whatsapp.outbound_service import lock_conversation_dispatch
from .admission import check_message_eligibility
from .repository import AgentOperationRepository


async def lock_message_operation(
    session: AsyncSession, context: TenantContext, *, message_id: UUID
) -> bool:
    await set_tenant_context(session, context.tenant_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT c.whatsapp_account_id,c.customer_wa_id,adm.agent_instance_id "
                    "FROM public.messages m JOIN public.conversations c ON (c.tenant_id,c.id)=(m.tenant_id,m.conversation_id) "
                    "JOIN public.agent_message_admissions adm ON (adm.tenant_id,adm.source_event_id)=(m.tenant_id,m.source_event_id) "
                    "WHERE m.tenant_id=:t AND m.id=:m"
                ),
                {"t": context.tenant_id, "m": message_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["agent_instance_id"] is None:
        return False
    await lock_conversation_dispatch(
        session,
        tenant_id=context.tenant_id,
        account_id=row["whatsapp_account_id"],
        customer_wa_id=row["customer_wa_id"],
    )
    await lock_account_lifecycle(session, context.tenant_id, row["whatsapp_account_id"])
    await AgentOperationRepository(session, context).lock(row["agent_instance_id"])
    return await check_message_eligibility(session, context, message_id=message_id)


def guard_tool(
    tool: RuntimeTool, eligible: Callable[[], Awaitable[bool]]
) -> RuntimeTool:
    async def invoke(
        context: ToolInvocationContext, arguments: Mapping[str, object]
    ) -> object:
        if not await eligible():
            raise AgentRuntimeError("agent_operation_ineligible", retryable=False)
        return await tool.handler(context, arguments)

    return replace(tool, handler=invoke)
