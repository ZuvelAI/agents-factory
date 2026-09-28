from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import (
    JobEnvelope,
    JobHandler,
    configure_durable_worker,
)
from agents_factory.config import load_settings
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.whatsapp.account_service import (
    SessionFactoryMetaAccessTokenResolver,
)
from agents_factory.modules.whatsapp.contracts import MetaAccessTokenResolver
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.outbound_service import (
    OutboundMessageService,
    OutboundProvider,
)
from agents_factory.modules.whatsapp.sync_once import SyncType, request_sync_once


class InvalidOutboundJob(ValueError):
    pass


async def configure_outbound_worker(context: dict[Any, Any]) -> None:
    await configure_durable_worker(context)
    database = cast(Database, context["database"])
    settings = load_settings()
    key_provider = EnvironmentMasterKeyProvider(
        environment={"APP_MASTER_KEY": settings.app_master_key.get_secret_value()}
    )

    def meta_provider_for_session(
        session_factory: async_sessionmaker[AsyncSession],
    ) -> OutboundProvider:
        return MetaCloudApiProvider(
            app_secret=settings.meta_app_secret,
            access_tokens=SessionFactoryMetaAccessTokenResolver(
                session_factory=session_factory,
                key_provider=key_provider,
            ),
            graph_api_base_url=settings.meta_graph_api_base_url,
        )

    token_resolver = SessionFactoryMetaAccessTokenResolver(
        session_factory=database.session_factory,
        key_provider=key_provider,
    )
    injected_provider = context.get("whatsapp_provider")
    provider = cast(
        OutboundProvider,
        injected_provider or meta_provider_for_session(database.session_factory),
    )
    provider_for_session = (
        None if injected_provider is not None else meta_provider_for_session
    )
    sync_provider = cast(
        MetaCloudApiProvider,
        context.get("whatsapp_sync_provider")
        or MetaCloudApiProvider(
            app_secret=settings.meta_app_secret,
            graph_api_base_url=settings.meta_graph_api_base_url,
        ),
    )

    async def prepare_text_handler(envelope: JobEnvelope) -> None:
        await handle_prepare_text(
            envelope=envelope,
            database=database,
            provider=provider,
        )

    async def send_handler(envelope: JobEnvelope) -> None:
        await handle_send(
            envelope=envelope,
            database=database,
            provider=provider,
            provider_for_session=provider_for_session,
        )

    async def request_sync_handler(envelope: JobEnvelope) -> None:
        await handle_request_sync(
            envelope=envelope,
            database=database,
            provider=sync_provider,
            token_resolver=token_resolver,
        )

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers["outbound.text"] = prepare_text_handler
    handlers["whatsapp.outbound.send"] = send_handler
    handlers["whatsapp.sync.request"] = request_sync_handler


async def handle_request_sync(
    *,
    envelope: JobEnvelope,
    database: Database,
    provider: MetaCloudApiProvider,
    token_resolver: MetaAccessTokenResolver,
) -> None:
    if envelope.kind != "whatsapp.sync.request":
        raise InvalidOutboundJob("unexpected sync request job kind")
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        payload = await session.scalar(
            text(
                "SELECT payload FROM public.outbox_jobs "
                "WHERE tenant_id=:tenant AND id=:job AND topic='whatsapp.sync.request'"
            ),
            {"tenant": envelope.tenant_id, "job": envelope.job_id},
        )
    if not isinstance(payload, Mapping):
        raise InvalidOutboundJob("sync request payload is unavailable")
    try:
        account_id = UUID(str(payload["whatsapp_account_id"]))
        sync_type = payload["sync_type"]
    except (KeyError, TypeError, ValueError):
        raise InvalidOutboundJob("sync request payload is invalid") from None
    if account_id != envelope.aggregate_id or payload.get("aggregate_id") != str(
        account_id
    ):
        raise InvalidOutboundJob("sync request aggregate does not match payload")
    if sync_type not in {"smb_app_state_sync", "history"}:
        raise InvalidOutboundJob("sync request type is invalid")
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        existing_state = await session.scalar(
            text(
                "SELECT state FROM public.whatsapp_sync_requests "
                "WHERE tenant_id=:tenant AND whatsapp_account_id=:account "
                "AND sync_type=:sync_type"
            ),
            {
                "tenant": envelope.tenant_id,
                "account": account_id,
                "sync_type": sync_type,
            },
        )
    if existing_state is not None:
        return  # Accepted or uncertain: neither may be sent again.
    context = _context(envelope)
    resolved_credential = await token_resolver.resolve(
        context=context,
        whatsapp_account_id=account_id,
    )

    async def send(phone_number_id: str, requested_type: SyncType) -> str:
        return await provider.request_app_data_sync(
            phone_number_id=phone_number_id,
            sync_type=requested_type,
            access_token=resolved_credential,
        )

    await request_sync_once(
        database.session_factory,
        tenant_id=envelope.tenant_id,
        account_id=account_id,
        sync_type=cast(SyncType, sync_type),
        send=send,
    )


async def handle_prepare_text(
    *,
    envelope: JobEnvelope,
    database: Database,
    provider: OutboundProvider,
) -> None:
    if envelope.kind != "outbound.text":
        raise InvalidOutboundJob("unexpected outbound preparation job kind")
    message_id = await _load_message_id(database=database, envelope=envelope)
    await OutboundMessageService(
        session_factory=database.session_factory,
        context=_context(envelope),
        provider=provider,
    ).prepare_text(message_id=message_id)


async def handle_send(
    *,
    envelope: JobEnvelope,
    database: Database,
    provider: OutboundProvider,
    provider_for_session: Callable[[async_sessionmaker[AsyncSession]], OutboundProvider]
    | None = None,
) -> None:
    if envelope.kind != "whatsapp.outbound.send":
        raise InvalidOutboundJob("unexpected outbound send job kind")
    message_id = await _load_message_id(database=database, envelope=envelope)
    await OutboundMessageService(
        session_factory=database.session_factory,
        context=_context(envelope),
        provider=provider,
        provider_for_session=provider_for_session,
    ).send(message_id)


async def _load_message_id(*, database: Database, envelope: JobEnvelope) -> UUID:
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        payload = await session.scalar(
            text(
                "SELECT payload FROM public.outbox_jobs "
                "WHERE tenant_id = :tenant_id AND id = :job_id"
            ),
            {"tenant_id": envelope.tenant_id, "job_id": envelope.job_id},
        )
    if not isinstance(payload, Mapping):
        raise InvalidOutboundJob("outbound job payload is unavailable")
    try:
        return UUID(str(payload["message_id"]))
    except (KeyError, TypeError, ValueError):
        raise InvalidOutboundJob("outbound message id is invalid") from None


def _context(envelope: JobEnvelope) -> TenantContext:
    # Internal service identity, not a user or an authorization grant. The
    # durable ledger, tenant RLS and account/secret bindings remain mandatory.
    # Stable per tenant for auditing; never supplied by the queue payload.
    return TenantContext(
        tenant_id=envelope.tenant_id,
        actor_id=uuid5(
            NAMESPACE_URL,
            f"urn:agents-factory:service:whatsapp-outbound:{envelope.tenant_id}",
        ),
        actor_type="system",
        correlation_id=envelope.job_id,
    )
