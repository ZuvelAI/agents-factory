from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.whatsapp.account_service import (
    WhatsAppAccountRepository,
    WhatsAppAccountSummary,
)
from agents_factory.modules.whatsapp.router import WhatsAppAccountResponse


@pytest.mark.asyncio
async def test_account_response_identifies_verified_number_for_its_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, other_tenant_id = new_uuid7(), new_uuid7()
    account_id, other_account_id = new_uuid7(), new_uuid7()
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        for current_tenant in (tenant_id, other_tenant_id):
            await session.execute(
                text(
                    "INSERT INTO public.tenants (id, slug, name, status) "
                    "VALUES (:id, :slug, 'Identity test', 'active')"
                ),
                {"id": current_tenant, "slug": f"identity-{current_tenant}"},
            )
        for current_tenant, current_account, phone_id, digits in (
            (tenant_id, account_id, "meta-phone-1", "15550783881"),
            (other_tenant_id, other_account_id, "meta-phone-2", "15550783882"),
        ):
            await session.execute(
                text(
                    "INSERT INTO public.whatsapp_accounts "
                    "(id, tenant_id, provider, waba_id, phone_number_id, "
                    "display_phone_digits, status, mode, coexistence_eligibility) "
                    "VALUES (:id, :tenant_id, 'meta', 'waba-identity', :phone_id, "
                    ":digits, 'active', 'COEXISTENCE', 'ELIGIBLE')"
                ),
                {
                    "id": current_account,
                    "tenant_id": current_tenant,
                    "phone_id": phone_id,
                    "digits": digits,
                },
            )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        context = TenantContext(
            tenant_id=tenant_id,
            actor_id=new_uuid7(),
            actor_type="platform_admin",
            correlation_id=new_uuid7(),
        )
        accounts = await WhatsAppAccountRepository(session).list_for_tenant(
            context=context
        )

    assert len(accounts) == 1
    response = WhatsAppAccountResponse.from_summary(
        WhatsAppAccountSummary.from_account(accounts[0])
    )
    assert response.id == account_id
    assert response.display_phone_digits == "15550783881"
    assert response.phone_number_id == "meta-phone-1"
