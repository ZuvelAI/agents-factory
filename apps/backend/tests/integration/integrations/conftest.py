from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.modules.integrations.oauth import (
    AuthorizationGrant,
    OAuthConfiguration,
    ProviderRegistry,
)
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret


class FakeCredentialProvider:
    def __init__(self, *, oauth: bool = True) -> None:
        self.oauth = (
            OAuthConfiguration(
                authorization_endpoint="https://accounts.example.test/authorize",
                client_id="fixture-client",
                redirect_uri="https://control.example.test/oauth/callback",
                allowed_scopes=frozenset({"calendar.events", "calendar.readonly"}),
            )
            if oauth
            else None
        )
        self.failure: Exception | None = None
        self.exchange_count = 0
        self.refresh_count = 0
        self.revoke_count = 0
        self.health_count = 0
        self.granted_scopes = ("calendar.events",)
        self.latest_verifier: ResolvedSecret | None = None

    def _grant(self) -> AuthorizationGrant:
        if self.failure is not None:
            raise self.failure
        return AuthorizationGrant(
            credential=ResolvedSecret(b"fixture-provider-access-and-refresh"),
            granted_scopes=self.granted_scopes,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def exchange(
        self, *, code: ResolvedSecret, verifier: ResolvedSecret
    ) -> AuthorizationGrant:
        self.exchange_count += 1
        self.latest_verifier = verifier
        assert code.reveal() == b"fixture-authorization-code"
        return self._grant()

    async def refresh(self, credential: ResolvedSecret) -> AuthorizationGrant:
        self.refresh_count += 1
        assert credential.reveal() == b"fixture-provider-access-and-refresh"
        return self._grant()

    async def revoke(self, credential: ResolvedSecret) -> None:
        self.revoke_count += 1
        if self.failure is not None:
            raise self.failure

    async def check_health(self, credential: ResolvedSecret) -> None:
        self.health_count += 1
        if self.failure is not None:
            raise self.failure


@dataclass
class IntegrationHarness:
    service: IntegrationService
    provider: FakeCredentialProvider
    api_provider: FakeCredentialProvider
    context: TenantContext
    other_context: TenantContext


@pytest.fixture
async def integrations(
    session_factory: async_sessionmaker[AsyncSession],
) -> IntegrationHarness:
    first, second = uuid4(), uuid4()
    async with session_factory.begin() as session:
        for tenant_id in (first, second):
            await session.execute(
                text(
                    "INSERT INTO public.tenants (id, slug, name) VALUES (:id, :slug, 'Task 22')"
                ),
                {"id": tenant_id, "slug": f"task22-{tenant_id}"},
            )
    provider = FakeCredentialProvider()
    api_provider = FakeCredentialProvider(oauth=False)
    registry = ProviderRegistry()
    registry.register("google_calendar", provider)
    registry.register("woocommerce", api_provider)
    key_provider = EnvironmentMasterKeyProvider(
        environment={"APP_MASTER_KEY": "B" * 42 + "A"}
    )
    return IntegrationHarness(
        service=IntegrationService(
            sessions=session_factory, key_provider=key_provider, providers=registry
        ),
        provider=provider,
        api_provider=api_provider,
        context=TenantContext(first, uuid4(), "platform_admin", uuid4()),
        other_context=TenantContext(second, uuid4(), "platform_admin", uuid4()),
    )
