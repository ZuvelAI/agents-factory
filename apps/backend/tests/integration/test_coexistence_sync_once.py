from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.queue import JobEnvelope
from agents_factory.common.security import AdminPrincipal
from agents_factory.database import set_tenant_context
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.whatsapp import sync_once
from agents_factory.modules.whatsapp import router as whatsapp_router
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from outbound_worker import jobs as outbound_jobs


async def seed_account(session_factory, *, verified_at, phone_number_id="123456"):
    tenant, account = uuid4(), uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id,slug,name) VALUES (:id,:slug,'Sync test')"
            ),
            {"id": tenant, "slug": str(tenant)},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts (id,tenant_id,provider,waba_id,phone_number_id,status,mode,coexistence_eligibility,verified_at) VALUES (:id,:tenant,'meta','sync-waba',:phone,'active','COEXISTENCE','ELIGIBLE',:verified_at)"
            ),
            {
                "id": account,
                "tenant": tenant,
                "phone": phone_number_id,
                "verified_at": verified_at,
            },
        )
    return tenant, account


async def test_sync_request_is_sent_once_and_retains_support_id(session_factory):
    tenant, account = await seed_account(session_factory, verified_at=datetime.now(UTC))
    calls = []

    async def send(phone, kind):
        calls.append((phone, kind))
        return "support-123"

    first = await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="history",
        send=send,
    )
    second = await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="history",
        send=send,
    )
    assert (first, second) == ("ACCEPTED", "ACCEPTED")
    assert calls == [("123456", "history")]
    async with session_factory.begin() as session:
        row = (
            await session.execute(
                text(
                    "SELECT state,request_id FROM public.whatsapp_sync_requests WHERE tenant_id=:tenant AND whatsapp_account_id=:account"
                ),
                {"tenant": tenant, "account": account},
            )
        ).one()
        assert row == ("ACCEPTED", "support-123")


async def test_uncertain_request_is_not_sent_twice(session_factory):
    tenant, account = await seed_account(session_factory, verified_at=datetime.now(UTC))
    calls = 0

    async def uncertain(phone, kind):
        nonlocal calls
        calls += 1
        raise RuntimeError("network outcome unknown")

    first = await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="smb_app_state_sync",
        send=uncertain,
    )
    second = await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="smb_app_state_sync",
        send=uncertain,
    )
    assert (first, second) == ("UNKNOWN", "UNKNOWN")
    assert calls == 1


async def test_expired_onboarding_cannot_start_one_shot_sync(session_factory):
    tenant, account = await seed_account(
        session_factory, verified_at=datetime.now(UTC) - timedelta(hours=25)
    )

    async def send(phone, kind):
        pytest.fail("expired account reached provider")

    with pytest.raises(ValueError, match="sync window"):
        await sync_once.request_sync_once(
            session_factory,
            tenant_id=tenant,
            account_id=account,
            sync_type="history",
            send=send,
        )


async def test_verified_coexistence_signup_queues_both_sync_types_once(session_factory):
    tenant, account = await seed_account(session_factory, verified_at=datetime.now(UTC))
    context = TenantContext(
        tenant_id=tenant,
        actor_id=uuid4(),
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )
    for _ in range(2):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await sync_once.enqueue_initial_sync(
                session, context=context, account_id=account
            )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await set_tenant_context(session, tenant)
        jobs = (
            (
                await session.execute(
                    text("SELECT topic,payload FROM public.outbox_jobs ORDER BY id")
                )
            )
            .mappings()
            .all()
        )
        assert len(jobs) == 2
        assert {row["payload"]["sync_type"] for row in jobs} == {
            "history",
            "smb_app_state_sync",
        }
        assert {row["topic"] for row in jobs} == {"whatsapp.sync.request"}
        assert all(row["payload"]["aggregate_id"] == str(account) for row in jobs)
        assert all("token" not in str(row["payload"]).lower() for row in jobs)


async def test_api_only_account_does_not_queue_coexistence_sync(session_factory):
    tenant, account = await seed_account(session_factory, verified_at=datetime.now(UTC))
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET mode='API_ONLY' WHERE id=:account"
            ),
            {"account": account},
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        with pytest.raises(ValueError, match="coexistence"):
            await sync_once.enqueue_initial_sync(
                session,
                context=TenantContext(
                    tenant_id=tenant,
                    actor_id=uuid4(),
                    actor_type="platform_admin",
                    correlation_id=uuid4(),
                ),
                account_id=account,
            )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.outbox_jobs")) == 0
        )


async def test_sync_worker_records_meta_request_once_despite_job_replay(
    session_factory,
):
    tenant, account = await seed_account(session_factory, verified_at=datetime.now(UTC))
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await sync_once.enqueue_initial_sync(
            session,
            context=TenantContext(
                tenant_id=tenant,
                actor_id=uuid4(),
                actor_type="platform_admin",
                correlation_id=uuid4(),
            ),
            account_id=account,
        )
    async with session_factory.begin() as session:
        job_id = await session.scalar(
            text(
                "SELECT id FROM public.outbox_jobs WHERE payload->>'sync_type'='history' AND tenant_id=:tenant"
            ),
            {"tenant": tenant},
        )
    envelope = JobEnvelope(
        job_id=job_id,
        tenant_id=tenant,
        kind="whatsapp.sync.request",
        aggregate_id=account,
    )
    requests = []

    def meta_reply(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "request_id": "support-456",
            },
        )

    class TokenResolver:
        calls = 0

        async def resolve(self, *, context, whatsapp_account_id):
            assert (context.tenant_id, whatsapp_account_id) == (tenant, account)
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("credential no longer available after accepted sync")
            return ResolvedSecret(b"tenant-owned-test-token")

    resolver = TokenResolver()
    async with httpx.AsyncClient(transport=httpx.MockTransport(meta_reply)) as client:
        provider = MetaCloudApiProvider(
            app_secret=SecretStr("test-only"),
            http_client=client,
            graph_api_base_url="https://graph.facebook.com/v25.0",
        )
        for _ in range(2):
            await outbound_jobs.handle_request_sync(
                envelope=envelope,
                database=SimpleNamespace(session_factory=session_factory),
                provider=provider,
                token_resolver=resolver,
            )
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer tenant-owned-test-token"
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, tenant)
        row = (
            await session.execute(
                text(
                    "SELECT state,request_id FROM public.whatsapp_sync_requests "
                    "WHERE whatsapp_account_id=:account AND sync_type='history'"
                ),
                {"account": account},
            )
        ).one()
        assert row == ("ACCEPTED", "support-456")
        await set_tenant_context(session, uuid4())
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.whatsapp_sync_requests")
            )
            == 0
        )


async def test_sync_status_separates_unsent_uncertain_and_accepted(session_factory):
    tenant, account = await seed_account(session_factory, verified_at=datetime.now(UTC))
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        initial = await sync_once.get_sync_status(
            session, tenant_id=tenant, account_id=account
        )
    assert [(item.sync_type, item.state) for item in initial] == [
        ("smb_app_state_sync", "NOT_REQUESTED"),
        ("history", "NOT_REQUESTED"),
    ]

    async def uncertain(_phone, _kind):
        raise TimeoutError("provider outcome unknown")

    async def accepted(_phone, _kind):
        return "history-support-id"

    await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="smb_app_state_sync",
        send=uncertain,
    )
    await sync_once.request_sync_once(
        session_factory,
        tenant_id=tenant,
        account_id=account,
        sync_type="history",
        send=accepted,
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        statuses = await sync_once.get_sync_status(
            session, tenant_id=tenant, account_id=account
        )
        assert [(item.sync_type, item.state, item.request_id) for item in statuses] == [
            ("smb_app_state_sync", "UNKNOWN", None),
            ("history", "ACCEPTED", "history-support-id"),
        ]
        with pytest.raises(ValueError, match="account"):
            await sync_once.get_sync_status(
                session, tenant_id=uuid4(), account_id=account
            )


async def test_sync_status_route_hides_another_tenants_account(session_factory):
    _tenant, account = await seed_account(
        session_factory, verified_at=datetime.now(UTC)
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        with pytest.raises(DomainError) as error:
            await whatsapp_router.get_coexistence_sync_status(
                tenant_id=uuid4(),
                account_id=account,
                request=SimpleNamespace(),
                principal=AdminPrincipal(user_id=uuid4(), session_id=uuid4()),
                session=session,
            )
        assert error.value.status == 404


async def test_sync_observations_count_only_persisted_account_data(session_factory):
    tenant, account = await seed_account(session_factory, verified_at=datetime.now(UTC))
    other_tenant, other_account = await seed_account(
        session_factory, verified_at=datetime.now(UTC), phone_number_id="654321"
    )
    async with session_factory.begin() as session:
        for owner, owned_account in ((tenant, account), (other_tenant, other_account)):
            await session.execute(
                text(
                    "INSERT INTO public.whatsapp_contacts "
                    "(id,tenant_id,whatsapp_account_id,customer_wa_id,provider_timestamp) "
                    "VALUES (:id,:tenant,:account,:customer,now())"
                ),
                {
                    "id": uuid4(),
                    "tenant": owner,
                    "account": owned_account,
                    "customer": str(uuid4()),
                },
            )
        for digest in ("a", "b"):
            await session.execute(
                text(
                    "INSERT INTO public.whatsapp_history_inbox "
                    "(id,tenant_id,whatsapp_account_id,payload_digest,payload) "
                    "VALUES (:id,:tenant,:account,:digest,'{}'::jsonb)"
                ),
                {
                    "id": uuid4(),
                    "tenant": tenant,
                    "account": account,
                    "digest": digest * 64,
                },
            )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_history_import_receipts "
                "(id,tenant_id,whatsapp_account_id,inbox_id,outcome,progress,errors) "
                "SELECT :id,:tenant,:account,id,'IMPORTED','[]'::jsonb,'[]'::jsonb "
                "FROM public.whatsapp_history_inbox WHERE tenant_id=:tenant "
                "AND whatsapp_account_id=:account AND payload_digest=:digest"
            ),
            {
                "id": uuid4(),
                "tenant": tenant,
                "account": account,
                "digest": "a" * 64,
            },
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        observed = await sync_once.get_sync_observations(
            session, tenant_id=tenant, account_id=account
        )
        assert observed.active_contacts == 1
        assert observed.history_batches_received == 2
        assert observed.history_batches_imported == 1
        assert observed.history_batches_declined == 0
        assert observed.history_batches_pending == 1
        response = await whatsapp_router.get_coexistence_sync_observations(
            tenant_id=tenant,
            account_id=account,
            request=SimpleNamespace(),
            principal=AdminPrincipal(user_id=uuid4(), session_id=uuid4()),
            session=session,
        )
        assert response.history_batches_pending == 1
        with pytest.raises(ValueError, match="account"):
            await sync_once.get_sync_observations(
                session, tenant_id=other_tenant, account_id=account
            )
        with pytest.raises(DomainError) as error:
            await whatsapp_router.get_coexistence_sync_observations(
                tenant_id=other_tenant,
                account_id=account,
                request=SimpleNamespace(),
                principal=AdminPrincipal(user_id=uuid4(), session_id=uuid4()),
                session=session,
            )
        assert error.value.status == 404
