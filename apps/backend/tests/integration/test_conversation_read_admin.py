from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.security import (
    AdminPrincipal,
    PlatformAdminAuthorizer,
    require_platform_admin,
)
from agents_factory.dependencies import TransactionSession, get_transaction
from agents_factory.main import create_app


@pytest.mark.asyncio
async def test_conversation_reads_are_bounded_and_tenant_scoped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first, second, account, conversation, message = [uuid4() for _ in range(5)]
    async with session_factory.begin() as session:
        for tenant in (first, second):
            await session.execute(
                text(
                    "INSERT INTO public.tenants(id,slug,name) VALUES (:id,:slug,'Test')"
                ),
                {"id": tenant, "slug": str(tenant)},
            )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts(id,tenant_id,provider,waba_id,phone_number_id) VALUES (:id,:tenant,'meta','waba','phone')"
            ),
            {"id": account, "tenant": first},
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations(id,tenant_id,whatsapp_account_id,customer_wa_id) VALUES (:id,:tenant,:account,'CO.123')"
            ),
            {"id": conversation, "tenant": first, "account": account},
        )
        await session.execute(
            text(
                "INSERT INTO public.messages(id,tenant_id,conversation_id,direction,sender_type,message_type,content,provider_timestamp,arrival_sequence) VALUES (:id,:tenant,:conversation,'inbound','customer','text','{\"text\":\"prueba visible\"}',now(),1)"
            ),
            {"id": message, "tenant": first, "conversation": conversation},
        )
    app = create_app()

    async def transaction() -> AsyncIterator[AsyncSession]:
        async with session_factory.begin() as session:
            yield session

    async def admin(session: TransactionSession) -> AdminPrincipal:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.dependency_overrides[get_transaction] = transaction
    app.dependency_overrides[require_platform_admin] = admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get(f"/admin/tenants/{first}/conversations")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [str(conversation)]
        assert "access_token_secret_id" not in str(listed.json())
        empty = await client.get(f"/admin/tenants/{second}/conversations")
        assert empty.json() == []
        messages = await client.get(
            f"/admin/tenants/{first}/conversations/{conversation}/messages"
        )
        assert messages.status_code == 200
        assert messages.json()[0]["text"] == "prueba visible"
        denied = await client.get(
            f"/admin/tenants/{second}/conversations/{conversation}/messages"
        )
        assert denied.status_code == 404
        invalid = await client.get(f"/admin/tenants/{first}/conversations?limit=101")
        assert invalid.status_code == 422
    app.dependency_overrides.pop(require_platform_admin)

    class FakeVerifier:
        async def verify(self, access_jwt: str) -> AdminPrincipal:
            return AdminPrincipal(user_id=uuid4(), session_id=uuid4())

    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(FakeVerifier())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        unauthenticated = await client.get(f"/admin/tenants/{first}/conversations")
        assert unauthenticated.status_code == 401
