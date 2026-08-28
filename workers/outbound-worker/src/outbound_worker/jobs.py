from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

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
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider
from agents_factory.modules.whatsapp.outbound_service import (
    OutboundMessageService,
    OutboundProvider,
)


class InvalidOutboundJob(ValueError):
    pass


async def configure_outbound_worker(context: dict[Any, Any]) -> None:
    await configure_durable_worker(context)
    database = cast(Database, context["database"])
    settings = load_settings()
    key_provider = EnvironmentMasterKeyProvider(
        environment={"APP_MASTER_KEY": settings.app_master_key.get_secret_value()}
    )
    provider = cast(
        OutboundProvider,
        context.get("whatsapp_provider")
        or MetaCloudApiProvider(
            app_secret=settings.meta_app_secret,
            access_tokens=SessionFactoryMetaAccessTokenResolver(
                session_factory=database.session_factory,
                key_provider=key_provider,
            ),
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
        )

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers["outbound.text"] = prepare_text_handler
    handlers["whatsapp.outbound.send"] = send_handler


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
) -> None:
    if envelope.kind != "whatsapp.outbound.send":
        raise InvalidOutboundJob("unexpected outbound send job kind")
    message_id = await _load_message_id(database=database, envelope=envelope)
    await OutboundMessageService(
        session_factory=database.session_factory,
        context=_context(envelope),
        provider=provider,
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
    return TenantContext(
        tenant_id=envelope.tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=envelope.job_id,
    )
