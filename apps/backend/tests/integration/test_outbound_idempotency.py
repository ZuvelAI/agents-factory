from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import httpx
from pydantic import SecretStr
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.secrets.contracts import SecretAccessDenied
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.secrets.repository import SecretVault
from agents_factory.modules.whatsapp.account_service import (
    SessionFactoryMetaAccessTokenResolver,
)
from agents_factory.modules.whatsapp.contracts import (
    OutboundTemplateRequest,
    OutboundTextRequest,
    ProviderMessageResult,
    WhatsAppDeliveryStatusEvent,
    WhatsAppMobileEcho,
)
from agents_factory.modules.whatsapp.outbound_service import (
    OutboundMessageService,
    OutboundStatusReconciler,
)
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.mobile_echo import (
    ingest_mobile_echo,
    resume_ai_from_mobile,
)
from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping
from agents_factory.modules.whatsapp.signup_service import ACCESS_TOKEN_PURPOSE


class RecordingProvider:
    def __init__(self, results: Sequence[ProviderMessageResult]) -> None:
        self._results = list(results)
        self.text_requests: list[OutboundTextRequest] = []

    async def send_text(self, request: OutboundTextRequest) -> ProviderMessageResult:
        self.text_requests.append(request)
        return self._results.pop(0)

    async def send_template(
        self,
        request: OutboundTemplateRequest,
    ) -> ProviderMessageResult:
        raise AssertionError(f"unexpected template send: {request}")


async def test_dispatch_fence_does_not_exhaust_connection_pool(
    session_factory, local_database_url
):
    tenant, _, _, assistant = await _seed_text_reply(session_factory)
    engine = create_async_engine(
        local_database_url, pool_size=1, max_overflow=0, pool_timeout=0.2
    )
    try:
        service = OutboundMessageService(
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
            context=_context(tenant),
            provider=RecordingProvider(
                [
                    ProviderMessageResult(
                        outcome="accepted", provider_message_id="wamid.one-connection"
                    )
                ]
            ),
        )
        prepared = await service.prepare_text(message_id=assistant)
        assert (await service.send(prepared)).status == "ACCEPTED"
    finally:
        await engine.dispose()


async def test_production_style_token_lookup_uses_reserved_dispatch_connection(
    session_factory, local_database_url
):
    tenant, _, _, assistant = await _seed_text_reply(session_factory)
    engine = create_async_engine(
        local_database_url, pool_size=1, max_overflow=0, pool_timeout=0.2
    )

    class DatabaseTokenResolver:
        def __init__(self, factory):
            self.factory = factory

        async def resolve(self, *, context, whatsapp_account_id):
            async with self.factory.begin() as session:
                await session.scalar(text("SELECT 1"))
            return ResolvedSecret(b"test-only-token")

    sent: list[httpx.Request] = []

    def accept(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.pool-one"}]})

    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with httpx.AsyncClient(transport=httpx.MockTransport(accept)) as client:
            provider = MetaCloudApiProvider(
                app_secret=SecretStr("test-only-app-secret"),
                access_tokens=DatabaseTokenResolver(factory),
                http_client=client,
                graph_api_base_url="https://graph.facebook.com/v25.0",
            )
            service = OutboundMessageService(
                session_factory=factory,
                context=_context(tenant),
                provider=provider,
                provider_for_session=lambda bound_factory: replace(
                    provider,
                    access_tokens=DatabaseTokenResolver(bound_factory),
                ),
            )
            prepared = await service.prepare_text(message_id=assistant)
            result = await service.send(prepared)
        assert result.status == "ACCEPTED"
        assert len(sent) == 1
    finally:
        await engine.dispose()


async def test_encrypted_meta_token_lookup_uses_reserved_dispatch_connection(
    session_factory, local_database_url
):
    tenant, account, _, assistant = await _seed_text_reply(session_factory)
    context = TenantContext(
        tenant_id=tenant,
        actor_id=new_uuid7(),
        actor_type="platform_admin",
        correlation_id=new_uuid7(),
    )
    encoded_key = base64.urlsafe_b64encode(b"\x07" * 32).rstrip(b"=").decode()
    key_provider = EnvironmentMasterKeyProvider(
        environment={"APP_MASTER_KEY": encoded_key}
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        secret_ref = await SecretVault.for_session(
            session, key_provider=key_provider
        ).store(
            context=context,
            purpose=ACCESS_TOKEN_PURPOSE,
            record_context=f"whatsapp_account:{account}",
            plaintext=b"test-only-encrypted-meta-token",
        )
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts "
                "SET access_token_secret_id=:secret_id WHERE id=:account_id"
            ),
            {"secret_id": secret_ref.id, "account_id": account},
        )

    engine = create_async_engine(
        local_database_url, pool_size=1, max_overflow=0, pool_timeout=0.2
    )
    sent: list[httpx.Request] = []

    def accept(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        assert (
            request.headers["Authorization"] == "Bearer test-only-encrypted-meta-token"
        )
        return httpx.Response(200, json={"messages": [{"id": "wamid.vault-pool-one"}]})

    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with httpx.AsyncClient(transport=httpx.MockTransport(accept)) as client:
            provider = MetaCloudApiProvider(
                app_secret=SecretStr("test-only-app-secret"),
                access_tokens=SessionFactoryMetaAccessTokenResolver(
                    session_factory=factory, key_provider=key_provider
                ),
                http_client=client,
                graph_api_base_url="https://graph.facebook.com/v25.0",
            )
            service = OutboundMessageService(
                session_factory=factory,
                context=context,
                provider=provider,
                provider_for_session=lambda bound_factory: replace(
                    provider,
                    access_tokens=SessionFactoryMetaAccessTokenResolver(
                        session_factory=bound_factory, key_provider=key_provider
                    ),
                ),
            )
            prepared = await service.prepare_text(message_id=assistant)
            result = await service.send(prepared)
        assert result.status == "ACCEPTED"
        assert len(sent) == 1
    finally:
        await engine.dispose()


async def test_reserved_token_lookup_denial_is_committed_without_second_connection(
    session_factory, local_database_url
):
    tenant, account, _, _ = await _seed_text_reply(session_factory)
    context = TenantContext(
        tenant_id=tenant,
        actor_id=new_uuid7(),
        actor_type="system",
        correlation_id=new_uuid7(),
    )
    encoded_key = base64.urlsafe_b64encode(b"\x08" * 32).rstrip(b"=").decode()
    key_provider = EnvironmentMasterKeyProvider(
        environment={"APP_MASTER_KEY": encoded_key}
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        secret_ref = await SecretVault.for_session(
            session, key_provider=key_provider
        ).store(
            context=context,
            purpose=ACCESS_TOKEN_PURPOSE,
            record_context="whatsapp_account:a-different-account",
            plaintext=b"test-only-inaccessible-token",
        )
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts "
                "SET access_token_secret_id=:secret_id WHERE id=:account_id"
            ),
            {"secret_id": secret_ref.id, "account_id": account},
        )

    engine = create_async_engine(
        local_database_url, pool_size=1, max_overflow=0, pool_timeout=0.2
    )
    try:
        async with engine.connect() as connection:
            factory = async_sessionmaker(connection, expire_on_commit=False)
            resolver = SessionFactoryMetaAccessTokenResolver(
                session_factory=factory, key_provider=key_provider
            )
            with pytest.raises(SecretAccessDenied):
                await resolver.resolve(context=context, whatsapp_account_id=account)
        async with engine.connect() as connection:
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events "
                    "WHERE tenant_id=:tenant_id AND event_type='secret.access_denied'"
                ),
                {"tenant_id": tenant},
            )
        assert count == 1
    finally:
        await engine.dispose()


async def test_queued_ai_reply_before_mobile_takeover_cannot_send_after_resume(
    session_factory,
):
    tenant, account, conversation, assistant = await _seed_text_reply(session_factory)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET mode='COEXISTENCE', "
                "coexistence_eligibility='ELIGIBLE' WHERE id=:id"
            ),
            {"id": account},
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await ingest_mobile_echo(
            session,
            context=_context(tenant),
            mapping=WhatsAppAccountMapping(account_id=account, tenant_id=tenant),
            event=WhatsAppMobileEcho(
                waba_id=f"waba-{account.hex}",
                phone_number_id=f"phone-{account.hex}",
                whatsapp_message_id="wamid.takeover.before-prepare",
                recipient_wa_id="573000000001",
                message_type="text",
                content={"text": "Yo atiendo ahora"},
                occurred_at=datetime.now(UTC),
            ),
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        version = await session.scalar(
            text("SELECT state_version FROM public.conversations WHERE id=:id"),
            {"id": conversation},
        )
        await resume_ai_from_mobile(
            session,
            context=TenantContext(
                tenant_id=tenant,
                actor_id=new_uuid7(),
                actor_type="platform_admin",
                correlation_id=new_uuid7(),
            ),
            account_id=account,
            conversation_id=conversation,
            expected_version=version,
        )

    provider = RecordingProvider([])
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant),
        provider=provider,
    )
    with pytest.raises(LookupError):
        await service.prepare_text(message_id=assistant)
    async with session_factory.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.outbound_messages"))
            == 0
        )
    assert provider.text_requests == []


async def test_late_materialized_older_inbound_cannot_prepare_ai_after_resume(
    session_factory,
):
    inbound_at = datetime.now(UTC) - timedelta(minutes=1)
    tenant, account, conversation, assistant = await _seed_text_reply(
        session_factory, inbound_at=inbound_at
    )
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET mode='COEXISTENCE', "
                "coexistence_eligibility='ELIGIBLE' WHERE id=:id"
            ),
            {"id": account},
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await ingest_mobile_echo(
            session,
            context=_context(tenant),
            mapping=WhatsAppAccountMapping(account_id=account, tenant_id=tenant),
            event=WhatsAppMobileEcho(
                waba_id=f"waba-{account.hex}",
                phone_number_id=f"phone-{account.hex}",
                whatsapp_message_id="wamid.takeover.late-inbound",
                recipient_wa_id="573000000001",
                message_type="text",
                content={"text": "Ya lo atiendo"},
                occurred_at=inbound_at + timedelta(seconds=10),
            ),
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        version = await session.scalar(
            text("SELECT state_version FROM public.conversations WHERE id=:id"),
            {"id": conversation},
        )
        await resume_ai_from_mobile(
            session,
            context=TenantContext(
                tenant_id=tenant,
                actor_id=new_uuid7(),
                actor_type="platform_admin",
                correlation_id=new_uuid7(),
            ),
            account_id=account,
            conversation_id=conversation,
            expected_version=version,
        )
    async with session_factory.begin() as session:
        inbound_update = await session.execute(
            text(
                "UPDATE public.messages SET arrival_sequence=4 "
                "WHERE conversation_id=:conversation AND direction='inbound'"
            ),
            {"conversation": conversation},
        )
        assert inbound_update.rowcount == 1
        assistant_update = await session.execute(
            text("UPDATE public.messages SET arrival_sequence=5 WHERE id=:assistant"),
            {"assistant": assistant},
        )
        assert assistant_update.rowcount == 1

    provider = RecordingProvider([])
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant),
        provider=provider,
    )
    with pytest.raises(LookupError):
        await service.prepare_text(message_id=assistant)
    assert provider.text_requests == []


async def test_cancelled_dispatch_releases_fence_and_retains_unknown_outcome(
    session_factory,
):
    from agents_factory.modules.whatsapp.outbound_service import (
        lock_conversation_dispatch,
    )

    tenant, account, _, assistant = await _seed_text_reply(session_factory)
    entered = asyncio.Event()

    class InterruptedProvider(RecordingProvider):
        async def send_text(self, request):
            entered.set()
            await asyncio.Event().wait()

    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant),
        provider=InterruptedProvider([]),
    )
    prepared = await service.prepare_text(message_id=assistant)
    sending = asyncio.create_task(service.send(prepared))
    try:
        await asyncio.wait_for(entered.wait(), 3)
    finally:
        sending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sending

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL lock_timeout='500ms'"))
        await lock_conversation_dispatch(
            session, tenant_id=tenant, account_id=account, customer_wa_id="573000000001"
        )
    # A retry must not dispatch again when the first provider outcome is unknown.
    assert (await service.send(prepared)).status == "UNCERTAIN"


async def test_mobile_reply_blocks_prepared_ai_send(session_factory) -> None:
    from agents_factory.modules.whatsapp.contracts import WhatsAppMobileEcho
    from agents_factory.modules.whatsapp.mobile_echo import ingest_mobile_echo
    from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping

    tenant, account, conversation, assistant = await _seed_text_reply(session_factory)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET mode='COEXISTENCE', coexistence_eligibility='ELIGIBLE' WHERE id=:id"
            ),
            {"id": account},
        )
    provider = RecordingProvider([])
    outbound = OutboundMessageService(
        session_factory=session_factory, context=_context(tenant), provider=provider
    )
    prepared = await outbound.prepare_text(message_id=assistant)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await ingest_mobile_echo(
            session,
            context=_context(tenant),
            mapping=WhatsAppAccountMapping(account_id=account, tenant_id=tenant),
            event=WhatsAppMobileEcho(
                waba_id=f"waba-{account.hex}",
                phone_number_id=f"phone-{account.hex}",
                whatsapp_message_id="wamid.human",
                recipient_wa_id="573000000001",
                message_type="text",
                content={"text": "Yo me encargo"},
                occurred_at=datetime.now(UTC),
            ),
        )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT status FROM public.outbound_messages WHERE id=:id"),
                {"id": prepared},
            )
            == "BLOCKED"
        )
    result = await outbound.send(prepared)
    assert result.status == "BLOCKED"
    assert provider.text_requests == []


def _context(tenant_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=new_uuid7(),
    )


async def test_mobile_takeover_serializes_with_inflight_dispatch(
    session_factory,
) -> None:
    from agents_factory.modules.whatsapp.contracts import WhatsAppMobileEcho
    from agents_factory.modules.whatsapp.mobile_echo import ingest_mobile_echo
    from agents_factory.modules.whatsapp.repository import WhatsAppAccountMapping

    tenant, account, conversation, assistant = await _seed_text_reply(session_factory)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.whatsapp_accounts SET mode='COEXISTENCE', coexistence_eligibility='ELIGIBLE' WHERE id=:id"
            ),
            {"id": account},
        )
    entered, release, takeover_started = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    class PausedProvider(RecordingProvider):
        async def send_text(self, request):
            entered.set()
            await release.wait()
            return ProviderMessageResult(
                outcome="accepted", provider_message_id="wamid.inflight"
            )

    outbound = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant),
        provider=PausedProvider([]),
    )
    prepared = await outbound.prepare_text(message_id=assistant)

    async def takeover():
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            takeover_started.set()
            await ingest_mobile_echo(
                session,
                context=_context(tenant),
                mapping=WhatsAppAccountMapping(account_id=account, tenant_id=tenant),
                event=WhatsAppMobileEcho(
                    waba_id=f"waba-{account.hex}",
                    phone_number_id=f"phone-{account.hex}",
                    whatsapp_message_id="wamid.human.concurrent",
                    recipient_wa_id="573000000001",
                    message_type="text",
                    content={"text": "Yo me encargo"},
                    occurred_at=datetime.now(UTC),
                ),
            )

    sending = asyncio.create_task(outbound.send(prepared))
    mobile = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        mobile = asyncio.create_task(takeover())
        await asyncio.wait_for(takeover_started.wait(), 3)
        # A committed takeover must never race an already-claimed provider call.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(mobile), 0.2)
    finally:
        release.set()
        await asyncio.wait_for(sending, 3)
        if mobile is not None:
            await asyncio.wait_for(mobile, 3)
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT control_state FROM public.conversations WHERE id=:id"),
                {"id": conversation},
            )
            == "HUMAN_ACTIVE"
        )
        assert (
            await session.scalar(
                text("SELECT status FROM public.outbound_messages WHERE id=:id"),
                {"id": prepared},
            )
            == "ACCEPTED"
        )


async def _seed_text_reply(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    inbound_at: datetime | None = None,
) -> tuple[UUID, UUID, UUID, UUID]:
    tenant_id = new_uuid7()
    account_id = new_uuid7()
    conversation_id = new_uuid7()
    inbound_id = new_uuid7()
    assistant_id = new_uuid7()
    agent_spec_id = new_uuid7()
    occurred_at = inbound_at or datetime.now(UTC)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) VALUES "
                "(:id, :slug, 'Outbound Tenant', 'active')"
            ),
            {"id": tenant_id, "slug": f"outbound-{tenant_id.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, status) "
                "VALUES (:id, :tenant_id, 'meta', :waba_id, :phone_number_id, "
                "'active')"
            ),
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "waba_id": f"waba-{account_id.hex}",
                "phone_number_id": f"phone-{account_id.hex}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations "
                "(id, tenant_id, whatsapp_account_id, customer_wa_id) "
                "VALUES (:id, :tenant_id, :account_id, '573000000001')"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "account_id": account_id,
            },
        )
        insert_message = text(
            "INSERT INTO public.messages "
            "(id, tenant_id, conversation_id, in_reply_to_message_id, direction, "
            "sender_type, provider_message_id, message_type, content, "
            "provider_timestamp, arrival_sequence, agent_spec_id, "
            "agent_spec_version) VALUES "
            "(:id, :tenant_id, :conversation_id, :reply_to, :direction, "
            ":sender_type, :provider_message_id, 'text', :content, "
            ":provider_timestamp, :arrival_sequence, :agent_spec_id, "
            ":agent_spec_version)"
        ).bindparams(bindparam("content", type_=JSONB))
        await session.execute(
            insert_message,
            {
                "id": inbound_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "reply_to": None,
                "direction": "inbound",
                "sender_type": "customer",
                "provider_message_id": f"wamid.inbound.{inbound_id}",
                "content": {"text": "Hola"},
                "provider_timestamp": occurred_at,
                "arrival_sequence": 1,
                "agent_spec_id": None,
                "agent_spec_version": None,
            },
        )
        await session.execute(
            insert_message,
            {
                "id": assistant_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "reply_to": inbound_id,
                "direction": "outbound",
                "sender_type": "ai",
                "provider_message_id": None,
                "content": {"text": "Hola, ¿cómo puedo ayudarte?"},
                "provider_timestamp": occurred_at + timedelta(seconds=1),
                "arrival_sequence": 2,
                "agent_spec_id": agent_spec_id,
                "agent_spec_version": "m2-test",
            },
        )
    return tenant_id, account_id, conversation_id, assistant_id


@pytest.mark.asyncio
async def test_duplicate_prepare_and_send_produce_one_customer_message(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, _, _, assistant_id = await _seed_text_reply(session_factory)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="wamid.out.1")]
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant_id),
        provider=provider,
    )

    first_id = await service.prepare_text(message_id=assistant_id)
    duplicate_id = await service.prepare_text(message_id=assistant_id)
    first_send = await service.send(first_id)
    duplicate_send = await service.send(first_id)

    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status, provider_message_id, attempt_count, "
                        "status_history FROM public.outbound_messages"
                    )
                )
            )
            .mappings()
            .one()
        )
        send_jobs = await session.scalar(
            text(
                "SELECT count(*) FROM public.outbox_jobs "
                "WHERE topic = 'whatsapp.outbound.send'"
            )
        )

    assert duplicate_id == first_id
    assert first_send.status == "ACCEPTED"
    assert duplicate_send.status == "ACCEPTED"
    assert len(provider.text_requests) == 1
    assert row["provider_message_id"] == "wamid.out.1"
    assert row["attempt_count"] == 1
    assert [entry["status"] for entry in row["status_history"]] == [
        "PREPARED",
        "SENDING",
        "ACCEPTED",
    ]
    assert send_jobs == 1


@pytest.mark.asyncio
async def test_ambiguous_timeout_is_not_blindly_retried(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, _, _, assistant_id = await _seed_text_reply(session_factory)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="uncertain", error_code="provider_timeout")]
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant_id),
        provider=provider,
    )
    outbound_id = await service.prepare_text(message_id=assistant_id)

    first = await service.send(outbound_id)
    replay = await service.send(outbound_id)

    assert first.status == "UNCERTAIN"
    assert replay.status == "UNCERTAIN"
    assert len(provider.text_requests) == 1


@pytest.mark.asyncio
async def test_provider_rejection_is_persisted_without_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, _, _, assistant_id = await _seed_text_reply(session_factory)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="rejected", error_code="meta_131047")]
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant_id),
        provider=provider,
    )
    outbound_id = await service.prepare_text(message_id=assistant_id)

    rejected = await service.send(outbound_id)
    replay = await service.send(outbound_id)

    assert rejected.status == "FAILED"
    assert replay.status == "FAILED"
    assert rejected.error_code == "meta_131047"
    assert len(provider.text_requests) == 1


@pytest.mark.asyncio
async def test_send_rechecks_conversation_authority(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, _, conversation_id, assistant_id = await _seed_text_reply(
        session_factory
    )
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="wamid.never")]
    )
    service = OutboundMessageService(
        session_factory=session_factory,
        context=_context(tenant_id),
        provider=provider,
    )
    outbound_id = await service.prepare_text(message_id=assistant_id)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.conversations SET control_state = 'HUMAN_ACTIVE' "
                "WHERE id = :conversation_id"
            ),
            {"conversation_id": conversation_id},
        )

    result = await service.send(outbound_id)

    assert result.status == "BLOCKED"
    assert result.error_code == "conversation_authority_unavailable"
    assert provider.text_requests == []


@pytest.mark.asyncio
async def test_delivery_callbacks_preserve_history_and_cost_attribution(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, account_id, _, assistant_id = await _seed_text_reply(session_factory)
    provider = RecordingProvider(
        [ProviderMessageResult(outcome="accepted", provider_message_id="wamid.out.2")]
    )
    context = _context(tenant_id)
    service = OutboundMessageService(
        session_factory=session_factory,
        context=context,
        provider=provider,
    )
    outbound_id = await service.prepare_text(message_id=assistant_id)
    await service.send(outbound_id)

    occurred_at = datetime.now(UTC)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        reconciler = OutboundStatusReconciler(session)
        for offset, status in enumerate(("delivered", "read", "failed")):
            reconciled = await reconciler.reconcile(
                context=context,
                whatsapp_account_id=account_id,
                event=WhatsAppDeliveryStatusEvent(
                    waba_id="waba-test",
                    phone_number_id="phone-test",
                    whatsapp_message_id="wamid.out.2",
                    recipient_wa_id="573000000001",
                    status=status,
                    occurred_at=occurred_at + timedelta(seconds=offset),
                    raw_payload={},
                    error_code="meta_131026" if status == "failed" else None,
                    cost_attribution={
                        "billable": True,
                        "category": "service",
                        "pricing_model": "CBP",
                    }
                    if status == "delivered"
                    else {},
                ),
            )
            assert reconciled is True

    async with session_factory.begin() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status, status_history, cost_attribution, "
                        "provider_error_code FROM public.outbound_messages "
                        "WHERE id = :id"
                    ),
                    {"id": outbound_id},
                )
            )
            .mappings()
            .one()
        )

    assert row["status"] == "READ"
    assert [entry["status"] for entry in row["status_history"]][-3:] == [
        "DELIVERED",
        "READ",
        "FAILED",
    ]
    assert row["cost_attribution"] == {
        "billable": True,
        "category": "service",
        "pricing_model": "CBP",
    }
    assert row["provider_error_code"] == "meta_131026"
