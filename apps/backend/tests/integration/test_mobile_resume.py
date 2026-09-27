from uuid import uuid4
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.security import (
    AdminPrincipal,
    PlatformAdminAuthorizer,
    require_platform_admin,
)
from agents_factory.database import set_tenant_context
from agents_factory.dependencies import TransactionSession, get_transaction
from agents_factory.main import create_app
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.whatsapp import mobile_echo


async def test_explicit_admin_resume_is_audited_without_queuing_ai(session_factory):
    tenant, account, conversation, admin = uuid4(), uuid4(), uuid4(), uuid4()
    context = TenantContext(
        tenant_id=tenant,
        actor_id=admin,
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES (:id, :slug, 'Resume test')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, status, mode, coexistence_eligibility) "
                "VALUES (:id, :tenant, 'meta', 'waba-resume', 'phone-resume', 'active', 'COEXISTENCE', 'ELIGIBLE')"
            ),
            {"id": account, "tenant": tenant},
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations "
                "(id, tenant_id, whatsapp_account_id, customer_wa_id) "
                "VALUES (:id, :tenant, :account, '573000000001')"
            ),
            {"id": conversation, "tenant": tenant, "account": account},
        )
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )
        await service.request_handoff(conversation_id=conversation, reason="test_setup")
        await service.activate_human(conversation_id=conversation, reason="test_setup")

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )
        resumed = await service.resume_ai(
            conversation_id=conversation, reason="operator_resumed"
        )
        assert resumed.control_state.value == "AI_ACTIVE"
        assert resumed.state_version == 4

    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT actor_id, actor_type, reason FROM public.conversation_state_events "
                        "WHERE tenant_id=:tenant AND conversation_id=:conversation AND version=4"
                    ),
                    {"tenant": tenant, "conversation": conversation},
                )
            )
            .mappings()
            .one()
        )
        assert row == {
            "actor_id": admin,
            "actor_type": "platform_admin",
            "reason": "operator_resumed",
        }
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.outbox_jobs WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
            == 0
        )


async def test_system_actor_cannot_resume_human_control(session_factory):
    tenant = uuid4()
    context = TenantContext(
        tenant_id=tenant, actor_id=None, actor_type="system", correlation_id=uuid4()
    )
    async with session_factory.begin() as session:
        service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )
        with pytest.raises(PermissionError):
            await service.resume_ai(conversation_id=uuid4(), reason="automatic_resume")


async def _seed_scoped_human_conversation(session_factory):
    tenant, account, conversation = uuid4(), uuid4(), uuid4()
    context = TenantContext(
        tenant_id=tenant,
        actor_id=uuid4(),
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES (:id, :slug, 'Scoped resume')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, status, mode, coexistence_eligibility) "
                "VALUES (:id, :tenant, 'meta', 'waba-scoped', 'phone-scoped', 'active', 'COEXISTENCE', 'ELIGIBLE')"
            ),
            {"id": account, "tenant": tenant},
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations "
                "(id, tenant_id, whatsapp_account_id, customer_wa_id) "
                "VALUES (:id, :tenant, :account, '573000000002')"
            ),
            {"id": conversation, "tenant": tenant, "account": account},
        )
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )
        await service.request_handoff(conversation_id=conversation, reason="test_setup")
        await service.activate_human(conversation_id=conversation, reason="test_setup")
    return context, account, conversation


async def test_scoped_resume_requires_current_version_and_exact_active_coexistence_account(
    session_factory,
):
    context, account, conversation = await _seed_scoped_human_conversation(
        session_factory
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        for candidate_account, version in ((uuid4(), 3), (account, 2)):
            with pytest.raises(DomainError) as failure:
                await mobile_echo.resume_ai_from_mobile(
                    session,
                    context=context,
                    account_id=candidate_account,
                    conversation_id=conversation,
                    expected_version=version,
                )
            assert failure.value.status in {404, 409}
        resumed = await mobile_echo.resume_ai_from_mobile(
            session,
            context=context,
            account_id=account,
            conversation_id=conversation,
            expected_version=3,
        )
        assert resumed.control_state.value == "AI_ACTIVE"
        assert resumed.state_version == 4


@pytest.mark.parametrize("change", ["inactive", "api_only"])
async def test_scoped_resume_rejects_ineligible_account(session_factory, change):
    context, account, conversation = await _seed_scoped_human_conversation(
        session_factory
    )
    async with session_factory.begin() as session:
        if change == "inactive":
            await session.execute(
                text(
                    "UPDATE public.whatsapp_accounts SET status='inactive' WHERE id=:id"
                ),
                {"id": account},
            )
        else:
            await session.execute(
                text(
                    "UPDATE public.whatsapp_accounts "
                    "SET mode='API_ONLY', coexistence_eligibility='UNKNOWN' WHERE id=:id"
                ),
                {"id": account},
            )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        with pytest.raises(DomainError) as failure:
            await mobile_echo.resume_ai_from_mobile(
                session,
                context=context,
                account_id=account,
                conversation_id=conversation,
                expected_version=3,
            )
        assert failure.value.status == 404


async def test_database_rechecks_account_before_direct_human_resume(session_factory):
    context, account, conversation = await _seed_scoped_human_conversation(
        session_factory
    )
    async with session_factory.begin() as session:
        await session.execute(
            text("UPDATE public.whatsapp_accounts SET status='inactive' WHERE id=:id"),
            {"id": account},
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )
        with pytest.raises(DBAPIError):
            await service.resume_ai(
                conversation_id=conversation, reason="stale_admin_action"
            )


async def test_application_role_cannot_spoof_admin_human_resume(session_factory):
    context, _account, conversation = await _seed_scoped_human_conversation(
        session_factory
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, context.tenant_id)
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "SELECT * FROM agents_factory_private.transition_conversation_control("
                    ":event_id, :conversation_id, 'HUMAN_ACTIVE', 'AI_ACTIVE', "
                    ":actor_id, 'platform_admin', 'spoofed_resume')"
                ),
                {
                    "event_id": uuid4(),
                    "conversation_id": conversation,
                    "actor_id": context.actor_id,
                },
            )


async def test_admin_resume_route_requires_fresh_version_and_exact_account(
    session_factory,
):
    context, account, conversation = await _seed_scoped_human_conversation(
        session_factory
    )
    app = create_app()

    async def transaction() -> AsyncIterator[AsyncSession]:
        async with session_factory.begin() as session:
            yield session

    async def admin(session: TransactionSession) -> AdminPrincipal:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        assert context.actor_id is not None
        return AdminPrincipal(user_id=context.actor_id, session_id=uuid4())

    app.dependency_overrides[get_transaction] = transaction
    app.dependency_overrides[require_platform_admin] = admin
    path = f"/admin/tenants/{context.tenant_id}/whatsapp/{account}/conversations/{conversation}/resume-ai"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        wrong_account = await client.post(
            path.replace(str(account), str(uuid4())), json={"expected_version": 3}
        )
        stale = await client.post(path, json={"expected_version": 2})
        success = await client.post(path, json={"expected_version": 3})
        duplicate = await client.post(path, json={"expected_version": 3})

    assert wrong_account.status_code == 404
    assert stale.status_code == 409
    assert success.status_code == 200
    assert success.json() == {
        "conversation_id": str(conversation),
        "control_state": "AI_ACTIVE",
        "state_version": 4,
    }
    assert duplicate.status_code == 409


async def test_resume_route_rejects_missing_admin_credentials(session_factory):
    app = create_app()

    class UnusedVerifier:
        async def verify(self, access_jwt: str) -> AdminPrincipal:
            raise AssertionError("No token should be verified without credentials")

    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(UnusedVerifier())

    async def transaction() -> AsyncIterator[AsyncSession]:
        async with session_factory.begin() as session:
            yield session

    app.dependency_overrides[get_transaction] = transaction
    path = (
        f"/admin/tenants/{uuid4()}/whatsapp/{uuid4()}/conversations/{uuid4()}/resume-ai"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json={"expected_version": 3})

    assert response.status_code == 401
