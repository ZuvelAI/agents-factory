from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.database import set_tenant_context
from agents_factory.modules.integrations.models import IntegrationError
from agents_factory.modules.integrations.oauth import ProviderFailure
from agents_factory.modules.secrets.contracts import SecretAccessDenied
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.repository import SecretVault

from agents_factory.modules.secrets.redaction import ResolvedSecret
from .conftest import IntegrationHarness
from .test_oauth_lifecycle import _complete, _start


async def test_outage_and_expiry_only_affect_their_connection(
    integrations: IntegrationHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    harness = integrations
    admin_session = uuid4()
    calendar = await _complete(
        harness, await _start(harness, admin_session), admin_session
    )
    orders = await harness.service.connect_api_key(
        context=harness.context,
        connector_name="woocommerce",
        credential=ResolvedSecret(b"fixture-commerce-credential"),
    )
    harness.provider.failure = ProviderFailure("provider_unavailable")
    failed = await harness.service.check_health(
        context=harness.context, connection_id=calendar.id
    )
    healthy = await harness.service.check_health(
        context=harness.context, connection_id=orders.id
    )
    assert failed.health.status == "ERROR"
    assert healthy.health.status == "HEALTHY"
    harness.provider.failure = None
    assert (
        await harness.service.check_health(
            context=harness.context, connection_id=calendar.id
        )
    ).health.status == "HEALTHY"
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.integration_connections SET expires_at = now() - interval '1 minute' WHERE id = :id"
            ),
            {"id": calendar.id},
        )
    count = harness.provider.health_count
    expired = await harness.service.check_health(
        context=harness.context, connection_id=calendar.id
    )
    assert expired.status == "REAUTH_REQUIRED"
    assert harness.provider.health_count == count
    assert (
        await harness.service.refresh(
            context=harness.context, connection_id=calendar.id
        )
    ).status == "CONNECTED"


async def test_failed_provider_revoke_is_durably_disabled_and_retryable(
    integrations: IntegrationHarness,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = integrations
    connected = await harness.service.connect_api_key(
        context=harness.context,
        connector_name="woocommerce",
        credential=ResolvedSecret(b"fixture-commerce-credential"),
    )

    async def failing_revoke(credential: ResolvedSecret) -> None:
        async with session_factory.begin() as session:
            assert (
                await session.scalar(
                    text(
                        "SELECT status FROM public.integration_connections WHERE id = :id"
                    ),
                    {"id": connected.id},
                )
                == "REVOKING"
            )
        raise RuntimeError("fixture-commerce-credential")

    with monkeypatch.context() as patch:
        patch.setattr(harness.api_provider, "revoke", failing_revoke)
        pending = await harness.service.revoke(
            context=harness.context, connection_id=connected.id
        )
    assert pending.status == "REVOKING"
    assert "fixture-commerce-credential" not in pending.model_dump_json()
    before = harness.api_provider.health_count
    assert (
        await harness.service.check_health(
            context=harness.context, connection_id=connected.id
        )
    ).status == "REVOKING"
    assert harness.api_provider.health_count == before
    assert (
        await harness.service.revoke(
            context=harness.context, connection_id=connected.id
        )
    ).status == "REVOKED"


async def test_connection_and_secret_references_cannot_cross_tenants(
    integrations: IntegrationHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    harness = integrations
    connection_ids = []
    for context in (harness.context, harness.other_context):
        connection_ids.append(
            (
                await harness.service.connect_api_key(
                    context=context,
                    connector_name="woocommerce",
                    credential=ResolvedSecret(b"fixture-commerce-credential"),
                )
            ).id
        )
    with pytest.raises(IntegrationError) as error:
        await harness.service.revoke(
            context=harness.other_context, connection_id=connection_ids[0]
        )
    assert error.value.status == 404
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, harness.context.tenant_id)
        assert (
            await session.execute(text("SELECT id FROM public.integration_connections"))
        ).scalars().all() == [connection_ids[0]]
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "UPDATE public.integration_connections SET credential_secret_id = (SELECT credential_secret_id FROM public.integration_connections WHERE id = :other) WHERE id = :own"
                ),
                {"own": connection_ids[0], "other": connection_ids[1]},
            )
    # Same-tenant reference substitution also fails the vault's connection binding.
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        vault = SecretVault.for_session(
            session,
            key_provider=EnvironmentMasterKeyProvider(
                environment={"APP_MASTER_KEY": "B" * 42 + "A"}
            ),
        )
        reference = await vault.store(
            context=harness.context,
            purpose="integrations.woocommerce.credentials",
            record_context="integration_connection:wrong-binding",
            plaintext=b"fixture-wrong-binding",
        )
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.integration_connections SET credential_secret_id = :reference WHERE id = :id"
            ),
            {"reference": reference.id, "id": connection_ids[0]},
        )
    with pytest.raises(SecretAccessDenied):
        await harness.service.check_health(
            context=harness.context, connection_id=connection_ids[0]
        )
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.audit_events WHERE event_type = 'secret.access_denied'"
                )
            )
            == 1
        )
