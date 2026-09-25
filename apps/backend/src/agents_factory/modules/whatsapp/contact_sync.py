from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.contracts import WhatsAppContactChange
from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping


async def ingest_contact_change(
    session: AsyncSession,
    *,
    context: TenantContext,
    mapping: WhatsAppAccountMapping,
    event: WhatsAppContactChange,
) -> bool:
    """Mirror contacts only. Never create a conversation or request an AI turn."""
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
    if not allowed or context.tenant_id != mapping.tenant_id:
        raise DomainError(
            type="https://agents-factory.dev/problems/contact-sync-account",
            title="Invalid contact sync account",
            status=409,
            detail="An active coexistence account is required.",
            code="contact_sync_account_invalid",
        )
    removed = event.action == "remove"
    contact_id = await session.scalar(
        text(
            "INSERT INTO public.whatsapp_contacts (id, tenant_id, whatsapp_account_id, customer_wa_id, "
            "full_name, first_name, is_deleted, provider_timestamp) "
            "VALUES (:id, :tenant, :account, :customer, :full_name, :first_name, :removed, :timestamp) "
            "ON CONFLICT (tenant_id, whatsapp_account_id, customer_wa_id) DO UPDATE SET "
            "full_name=EXCLUDED.full_name, first_name=EXCLUDED.first_name, is_deleted=EXCLUDED.is_deleted, "
            "provider_timestamp=EXCLUDED.provider_timestamp, updated_at=now() "
            "WHERE EXCLUDED.provider_timestamp > whatsapp_contacts.provider_timestamp "
            "OR (EXCLUDED.provider_timestamp = whatsapp_contacts.provider_timestamp "
            "AND EXCLUDED.is_deleted AND NOT whatsapp_contacts.is_deleted) RETURNING id"
        ),
        {
            "id": new_uuid7(),
            "tenant": context.tenant_id,
            "account": mapping.account_id,
            "customer": event.customer_wa_id,
            "full_name": None if removed else event.full_name,
            "first_name": None if removed else event.first_name,
            "removed": removed,
            "timestamp": event.occurred_at,
        },
    )
    if contact_id is None:
        return False
    await AuditService(session).record(
        context=context,
        event_type="whatsapp.contact.synced",
        entity_type="whatsapp_contact",
        entity_id=contact_id,
        payload={
            "whatsapp_account_id": str(mapping.account_id),
            "action": event.action,
        },
    )
    return True
