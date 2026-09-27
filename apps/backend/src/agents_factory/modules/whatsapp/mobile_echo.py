from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.conversations.models import (
    AwaitingHumanPolicy,
    Conversation,
)
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.whatsapp.contracts import WhatsAppMobileEcho
from agents_factory.modules.whatsapp.outbound_service import (
    block_prepared_ai_replies,
    lock_conversation_dispatch,
)
from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping


async def ingest_mobile_echo(
    session: AsyncSession,
    *,
    context: TenantContext,
    mapping: WhatsAppAccountMapping,
    event: WhatsAppMobileEcho,
) -> bool:
    """Persist a human reply and take control atomically; never queue an AI turn."""
    await set_tenant_context(session, context.tenant_id)
    allowed = await session.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM public.whatsapp_accounts WHERE tenant_id=:tenant "
            "AND id=:account AND waba_id=:waba AND phone_number_id=:phone "
            "AND status='active' AND mode='COEXISTENCE')"
        ),
        {
            "tenant": context.tenant_id,
            "account": mapping.account_id,
            "waba": event.waba_id,
            "phone": event.phone_number_id,
        },
    )
    if not allowed or mapping.tenant_id != context.tenant_id:
        raise DomainError(
            type="https://agents-factory.dev/problems/mobile-echo-account",
            title="Invalid mobile account",
            status=409,
            detail="An active coexistence account is required.",
            code="mobile_echo_account_invalid",
        )
    await lock_conversation_dispatch(
        session,
        tenant_id=context.tenant_id,
        account_id=mapping.account_id,
        customer_wa_id=event.recipient_wa_id,
    )
    parameters = {
        "tenant": context.tenant_id,
        "account": mapping.account_id,
        "customer": event.recipient_wa_id,
    }
    created_id = await session.scalar(
        text(
            "INSERT INTO public.conversations (id, tenant_id, whatsapp_account_id, customer_wa_id, control_state) "
            "VALUES (:id, :tenant, :account, :customer, 'AI_ACTIVE') "
            "ON CONFLICT (tenant_id, whatsapp_account_id, customer_wa_id) DO NOTHING RETURNING id"
        ),
        {**parameters, "id": new_uuid7()},
    )
    conversation_id = await session.scalar(
        text(
            "SELECT id FROM public.conversations WHERE tenant_id=:tenant "
            "AND whatsapp_account_id=:account AND customer_wa_id=:customer FOR UPDATE"
        ),
        parameters,
    )
    if conversation_id is None:
        raise RuntimeError("Mobile conversation was not persisted")
    if created_id is not None:
        await session.execute(
            text(
                "INSERT INTO public.conversation_state_events "
                "(id, tenant_id, conversation_id, from_state, to_state, version, actor_type, reason) "
                "VALUES (:id, :tenant, :conversation, NULL, 'AI_ACTIVE', 1, 'system', 'mobile_reply_opened')"
            ),
            {
                "id": new_uuid7(),
                "tenant": context.tenant_id,
                "conversation": conversation_id,
            },
        )
    binding = {
        "tenant": context.tenant_id,
        "conversation": conversation_id,
        "provider_id": event.whatsapp_message_id,
    }
    duplicate = await session.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM public.messages WHERE tenant_id=:tenant "
            "AND conversation_id=:conversation AND provider_message_id=:provider_id)"
        ),
        binding,
    )
    if duplicate:
        return False
    message_id = new_uuid7()
    await session.execute(
        text(
            "INSERT INTO public.messages (id, tenant_id, conversation_id, direction, sender_type, "
            "provider_message_id, message_type, content, provider_timestamp, arrival_sequence) "
            "VALUES (:id, :tenant, :conversation, 'outbound', 'human', :provider_id, :type, :content, :timestamp, "
            "(SELECT coalesce(max(arrival_sequence),0)+1 FROM public.messages WHERE tenant_id=:tenant AND conversation_id=:conversation))"
        ).bindparams(bindparam("content", type_=JSONB)),
        {
            **binding,
            "id": message_id,
            "type": event.message_type,
            "content": event.content,
            "timestamp": event.occurred_at,
        },
    )
    await ConversationService(
        session=session,
        context=context,
        awaiting_human_policy=AwaitingHumanPolicy.SILENT,
    ).take_over_from_mobile(conversation_id=conversation_id)
    blocked = await block_prepared_ai_replies(
        session, context=context, conversation_id=conversation_id
    )
    await AuditService(session).record(
        context=context,
        event_type="conversation.mobile_reply.received",
        entity_type="message",
        entity_id=message_id,
        payload={
            "conversation_id": str(conversation_id),
            "source": "whatsapp_business_app",
            "blocked_ai_replies": blocked,
        },
    )
    return True


@dataclass(frozen=True, slots=True)
class HumanActiveConversation:
    conversation_id: UUID
    customer_hint: str
    state_version: int


async def list_human_active_mobile_conversations(
    session: AsyncSession,
    *,
    context: TenantContext,
    account_id: UUID,
) -> list[HumanActiveConversation]:
    """Return a bounded, masked admin view for one eligible coexistence account."""
    if context.actor_type != "platform_admin" or context.actor_id is None:
        raise PermissionError(
            "Human control visibility requires an identified administrator"
        )
    await set_tenant_context(session, context.tenant_id)
    binding = {"tenant": context.tenant_id, "account": account_id}
    account = await session.scalar(
        text(
            "SELECT id FROM public.whatsapp_accounts "
            "WHERE tenant_id=:tenant AND id=:account AND status='active' "
            "AND mode='COEXISTENCE' AND coexistence_eligibility='ELIGIBLE'"
        ),
        binding,
    )
    if account is None:
        raise DomainError(
            type="https://agents-factory.dev/problems/whatsapp-account-not-found",
            title="WhatsApp Account Not Found",
            status=404,
            detail="No active coexistence account was found.",
            code="whatsapp_account_not_found",
        )
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id AS conversation_id, "
                    "'***' || right(customer_wa_id, 4) AS customer_hint, state_version "
                    "FROM public.conversations "
                    "WHERE tenant_id=:tenant AND whatsapp_account_id=:account "
                    "AND control_state='HUMAN_ACTIVE' "
                    "ORDER BY updated_at DESC, id DESC LIMIT 20"
                ),
                binding,
            )
        )
        .mappings()
        .all()
    )
    return [
        HumanActiveConversation(
            conversation_id=row["conversation_id"],
            customer_hint=row["customer_hint"],
            state_version=row["state_version"],
        )
        for row in rows
    ]


async def resume_ai_from_mobile(
    session: AsyncSession,
    *,
    context: TenantContext,
    account_id: UUID,
    conversation_id: UUID,
    expected_version: int,
) -> Conversation:
    """Explicitly return one active coexistence conversation to AI control."""
    if context.actor_type != "platform_admin" or context.actor_id is None:
        raise PermissionError("AI resume requires an identified platform administrator")
    await set_tenant_context(session, context.tenant_id)
    binding = {
        "tenant": context.tenant_id,
        "account": account_id,
        "conversation": conversation_id,
    }
    customer_wa_id = await session.scalar(
        text(
            "SELECT customer_wa_id FROM public.conversations "
            "WHERE tenant_id=:tenant AND whatsapp_account_id=:account AND id=:conversation"
        ),
        binding,
    )
    if not isinstance(customer_wa_id, str):
        raise DomainError(
            type="https://agents-factory.dev/problems/conversation-not-found",
            title="Conversation Not Found",
            status=404,
            detail="No conversation was found for this WhatsApp account.",
            code="conversation_not_found",
        )
    await lock_conversation_dispatch(
        session,
        tenant_id=context.tenant_id,
        account_id=account_id,
        customer_wa_id=customer_wa_id,
    )
    row = (
        (
            await session.execute(
                text(
                    "SELECT conversation.control_state, conversation.state_version "
                    "FROM public.conversations AS conversation "
                    "JOIN public.whatsapp_accounts AS account "
                    "ON account.id=conversation.whatsapp_account_id "
                    "AND account.tenant_id=conversation.tenant_id "
                    "WHERE conversation.tenant_id=:tenant "
                    "AND conversation.whatsapp_account_id=:account "
                    "AND conversation.id=:conversation "
                    "AND account.status='active' AND account.mode='COEXISTENCE' "
                    "AND account.coexistence_eligibility='ELIGIBLE'"
                ),
                binding,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DomainError(
            type="https://agents-factory.dev/problems/conversation-not-found",
            title="Conversation Not Found",
            status=404,
            detail="No active coexistence conversation was found for this account.",
            code="conversation_not_found",
        )
    if (
        row["control_state"] != "HUMAN_ACTIVE"
        or row["state_version"] != expected_version
    ):
        raise DomainError(
            type="https://agents-factory.dev/problems/conversation-control-conflict",
            title="Conversation Control Changed",
            status=409,
            detail="Refresh the conversation before resuming AI control.",
            code="conversation_control_conflict",
        )
    return await ConversationService(
        session=session,
        context=context,
        awaiting_human_policy=AwaitingHumanPolicy.SILENT,
    ).resume_ai(conversation_id=conversation_id, reason="operator_resumed_mobile")
