"""Scoped live profiles; missing values and stale deliveries cannot erase data."""

from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from .contracts import InboundWhatsAppEvent

if TYPE_CHECKING:
    from .repository import WhatsAppAccountMapping


async def persist_contact_profile(
    session: AsyncSession,
    *,
    context: TenantContext,
    mapping: WhatsAppAccountMapping,
    event: InboundWhatsAppEvent,
) -> None:
    identity = event.contact_identity
    if not event.provider_timestamp_valid:
        return
    if identity is None or not any(
        (identity.profile_name, identity.username, identity.phone_number)
    ):
        return
    if context.tenant_id != mapping.tenant_id:
        raise ValueError("Contact profile tenant does not match account")
    await session.execute(
        text("""
        INSERT INTO public.whatsapp_contact_profiles
          (tenant_id,whatsapp_account_id,customer_wa_id,profile_name,username,phone_number,provider_timestamp)
        VALUES (:tenant,:account,:customer,:name,:username,:phone,:timestamp)
        ON CONFLICT (tenant_id,whatsapp_account_id,customer_wa_id) DO UPDATE SET
          profile_name=CASE WHEN EXCLUDED.provider_timestamp > whatsapp_contact_profiles.provider_timestamp
            THEN coalesce(EXCLUDED.profile_name,whatsapp_contact_profiles.profile_name)
            ELSE coalesce(whatsapp_contact_profiles.profile_name,EXCLUDED.profile_name) END,
          username=CASE WHEN EXCLUDED.provider_timestamp > whatsapp_contact_profiles.provider_timestamp
            THEN coalesce(EXCLUDED.username,whatsapp_contact_profiles.username)
            ELSE coalesce(whatsapp_contact_profiles.username,EXCLUDED.username) END,
          phone_number=CASE WHEN EXCLUDED.provider_timestamp > whatsapp_contact_profiles.provider_timestamp
            THEN coalesce(EXCLUDED.phone_number,whatsapp_contact_profiles.phone_number)
            ELSE coalesce(whatsapp_contact_profiles.phone_number,EXCLUDED.phone_number) END,
          provider_timestamp=EXCLUDED.provider_timestamp,updated_at=now()
        WHERE EXCLUDED.provider_timestamp >= whatsapp_contact_profiles.provider_timestamp
        """),
        {
            "tenant": context.tenant_id,
            "account": mapping.account_id,
            "customer": event.sender_wa_id,
            "name": identity.profile_name,
            "username": identity.username,
            "phone": identity.phone_number,
            "timestamp": event.occurred_at,
        },
    )
