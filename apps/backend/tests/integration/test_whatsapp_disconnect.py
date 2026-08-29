from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.contracts import SecretRef
from agents_factory.modules.secrets.repository import SecretVault
from agents_factory.modules.whatsapp.account_service import (
    WhatsAppAccountRepository,
    WhatsAppAccountService,
    WhatsAppDisconnectCoordinator,
)
from agents_factory.modules.whatsapp.contracts import (
    MetaEmbeddedSignupProvider,
    MetaHealthSnapshot,
)
from agents_factory.modules.whatsapp.signup_service import ACCESS_TOKEN_PURPOSE


NOW = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)


def _context(tenant_id: UUID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=new_uuid7(),
        actor_type="platform_admin",
        correlation_id=new_uuid7(),
    )


def _key_provider(byte: int) -> EnvironmentMasterKeyProvider:
    encoded = base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode()
    return EnvironmentMasterKeyProvider(environment={"APP_MASTER_KEY": encoded})


@dataclass
class _RevocationProvider:
    failure: Exception | None = None
    entered: asyncio.Event | None = None
    release: asyncio.Event | None = None
    calls: int = 0

    async def revoke(self, **_kwargs: object) -> None:
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure is not None:
            raise self.failure


@dataclass
class _BlockingHealthProvider:
    entered: asyncio.Event
    release: asyncio.Event

    async def inspect_health(self, **_kwargs: object) -> MetaHealthSnapshot:
        self.entered.set()
        await self.release.wait()
        return MetaHealthSnapshot(status="HEALTHY")


async def _seed_account(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    key_provider: EnvironmentMasterKeyProvider,
) -> tuple[TenantContext, UUID, SecretRef]:
    tenant_id = new_uuid7()
    account_id = new_uuid7()
    context = _context(tenant_id)
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name, status) "
                "VALUES (:id, :slug, 'Disconnect tenant', 'active')"
            ),
            {"id": tenant_id, "slug": f"disconnect-{tenant_id}"},
        )
        secret_ref = await SecretVault.for_session(
            session, key_provider=key_provider
        ).store(
            context=context,
            purpose=ACCESS_TOKEN_PURPOSE,
            record_context=f"whatsapp_account:{account_id}",
            plaintext=b"old-meta-token",
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, business_id, waba_id, phone_number_id, "
                "status, access_token_secret_id, mode, coexistence_eligibility, "
                "granted_scopes, health_status, verified_at) "
                "VALUES (:id, :tenant_id, 'meta', 'business-1', 'waba-1', "
                "'phone-1', 'active', :secret_id, 'API_ONLY', 'UNKNOWN', "
                "'[]'::jsonb, 'HEALTHY', :verified_at)"
            ),
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "secret_id": secret_ref.id,
                "verified_at": NOW,
            },
        )
    return context, account_id, secret_ref


async def _account_row(
    session_factory: async_sessionmaker[AsyncSession], account_id: UUID
) -> RowMapping:
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        return (
            await session.execute(
                text(
                    "SELECT status, access_token_secret_id, last_error_code "
                    "FROM public.whatsapp_accounts WHERE id = :account_id"
                ),
                {"account_id": account_id},
            )
        ).mappings().one()


async def _denial_count(
    session_factory: async_sessionmaker[AsyncSession], tenant_id: UUID
) -> int:
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        count = await session.scalar(
            text(
                "SELECT count(*) FROM public.audit_events "
                "WHERE tenant_id = :tenant_id AND event_type = 'secret.access_denied'"
            ),
            {"tenant_id": tenant_id},
        )
    assert isinstance(count, int)
    return count


@pytest.mark.asyncio
async def test_disconnect_keeps_inactive_cleared_mapping_when_vault_operations_fail(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stored_key = _key_provider(1)
    context, account_id, _secret_ref = await _seed_account(
        session_factory, key_provider=stored_key
    )
    provider = _RevocationProvider()

    await WhatsAppDisconnectCoordinator(
        session_factory=session_factory,
        key_provider=_key_provider(2),
        provider=cast(MetaEmbeddedSignupProvider, provider),
    ).revoke(context=context, account_id=account_id, revoked_at=NOW)

    row = await _account_row(session_factory, account_id)
    assert row["status"] == "inactive"
    assert row["access_token_secret_id"] is None
    assert row["last_error_code"] == "meta_revoke_pending"
    assert provider.calls == 0
    assert await _denial_count(session_factory, context.tenant_id) == 2


@pytest.mark.asyncio
async def test_second_revoke_preserves_pending_outcome_without_repeating_cleanup(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key_provider = _key_provider(3)
    context, account_id, _secret_ref = await _seed_account(
        session_factory, key_provider=key_provider
    )
    provider = _RevocationProvider(failure=RuntimeError("Meta unavailable"))
    coordinator = WhatsAppDisconnectCoordinator(
        session_factory=session_factory,
        key_provider=key_provider,
        provider=cast(MetaEmbeddedSignupProvider, provider),
    )

    await coordinator.revoke(
        context=context, account_id=account_id, revoked_at=NOW
    )
    await coordinator.revoke(
        context=context, account_id=account_id, revoked_at=NOW
    )

    row = await _account_row(session_factory, account_id)
    assert provider.calls == 1
    assert row["status"] == "inactive"
    assert row["access_token_secret_id"] is None
    assert row["last_error_code"] == "meta_revoke_pending"


@pytest.mark.asyncio
async def test_late_revoke_success_does_not_overwrite_a_reconnected_account(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key_provider = _key_provider(4)
    context, account_id, _secret_ref = await _seed_account(
        session_factory, key_provider=key_provider
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    provider = _RevocationProvider(entered=entered, release=release)
    coordinator = WhatsAppDisconnectCoordinator(
        session_factory=session_factory,
        key_provider=key_provider,
        provider=cast(MetaEmbeddedSignupProvider, provider),
    )

    revoke_task = asyncio.create_task(
        coordinator.revoke(
            context=context, account_id=account_id, revoked_at=NOW
        )
    )
    await entered.wait()
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        replacement_ref = await SecretVault.for_session(
            session, key_provider=key_provider
        ).store(
            context=context,
            purpose=ACCESS_TOKEN_PURPOSE,
            record_context=f"whatsapp_account:{account_id}",
            plaintext=b"new-meta-token",
        )
        await WhatsAppAccountRepository(session).connect_account(
            account_id=account_id,
            context=context,
            business_id="business-1",
            waba_id="waba-1",
            phone_number_id="phone-1",
            access_token_secret_ref=replacement_ref,
            mode="API_ONLY",
            coexistence_eligibility="UNKNOWN",
            granted_scopes=(),
            token_expires_at=None,
            verified_at=datetime(2026, 8, 28, 18, 1, tzinfo=UTC),
        )
    release.set()
    await revoke_task

    row = await _account_row(session_factory, account_id)
    assert provider.calls == 1
    assert row["status"] == "active"
    assert row["access_token_secret_id"] == replacement_ref.id
    assert row["last_error_code"] is None


@pytest.mark.asyncio
async def test_late_health_result_does_not_overwrite_disconnect_pending_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key_provider = _key_provider(5)
    context, account_id, _secret_ref = await _seed_account(
        session_factory, key_provider=key_provider
    )
    coordinator = WhatsAppDisconnectCoordinator(
        session_factory=session_factory,
        key_provider=key_provider,
        provider=cast(
            MetaEmbeddedSignupProvider,
            _RevocationProvider(failure=RuntimeError("Meta unavailable")),
        ),
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    health_provider = _BlockingHealthProvider(entered=entered, release=release)

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        accounts = WhatsAppAccountService(
            repository=WhatsAppAccountRepository(session),
            vault=SecretVault.for_session(session, key_provider=key_provider),
            provider=cast(MetaEmbeddedSignupProvider, health_provider),
            disconnect_executor=coordinator,
        )
        health_task = asyncio.create_task(
            accounts.check_health(
                context=context,
                account_id=account_id,
                checked_at=NOW,
            )
        )
        await entered.wait()
        await coordinator.revoke(
            context=context,
            account_id=account_id,
            revoked_at=NOW,
        )
        release.set()
        summary = await health_task

    row = await _account_row(session_factory, account_id)
    assert summary.status == "inactive"
    assert row["status"] == "inactive"
    assert row["access_token_secret_id"] is None
    assert row["last_error_code"] == "meta_revoke_pending"
