"""Read-only credential preflight for the fixed Zuvel review account; never sends."""
import asyncio
from uuid import UUID, uuid4

from agents_factory.common.queue import JobEnvelope
from agents_factory.config import load_settings
from agents_factory.database import Database
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.whatsapp.account_service import (
    SessionFactoryMetaAccessTokenResolver,
    WhatsAppAccountError,
)
from outbound_worker.jobs import _context


async def main() -> None:
    settings = load_settings()
    database = Database(settings.database_url)
    account_id = UUID("d4dfa61a-7ed6-4a87-877a-1d34e7dbf837")
    resolver = SessionFactoryMetaAccessTokenResolver(
        session_factory=database.session_factory,
        key_provider=EnvironmentMasterKeyProvider(environment={
            "APP_MASTER_KEY": settings.app_master_key.get_secret_value(),
        }),
    )
    try:
        job = JobEnvelope(
            job_id=uuid4(),
            tenant_id=UUID("c5cd8d04-01f2-49be-aa27-1075520a2a20"),
            kind="whatsapp.outbound.send", aggregate_id=account_id,
        )
        resolved = await resolver.resolve(
            context=_context(job), whatsapp_account_id=account_id,
        )
        assert resolved.reveal(), "empty credential"
        print("worker_credential_access=ok")
        other_job = JobEnvelope(
            job_id=uuid4(), tenant_id=uuid4(),
            kind="whatsapp.outbound.send", aggregate_id=account_id,
        )
        try:
            await resolver.resolve(
                context=_context(other_job), whatsapp_account_id=account_id,
            )
        except WhatsAppAccountError as error:
            assert error.code == "whatsapp_account_not_found"
            print("cross_tenant_access=blocked")
        else:
            raise RuntimeError("cross-tenant check failed")
        print("messages_sent=0")
    finally:
        await database.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print("preflight_failed=" + type(error).__name__)
        raise SystemExit(1) from None
