from __future__ import annotations

import asyncio
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.modules.integrations.models import IntegrationError
from agents_factory.modules.integrations.oauth import (
    AuthorizationGrant,
    OAuthStart,
    pkce_challenge,
    state_digest,
)
from agents_factory.modules.secrets.redaction import ResolvedSecret

from .conftest import IntegrationHarness


def _state(started: OAuthStart) -> str:
    return parse_qs(urlsplit(started.authorization_url).query)["state"][0]


async def _start(harness: IntegrationHarness, admin_session: UUID) -> OAuthStart:
    return await harness.service.start_oauth(
        context=harness.context,
        admin_session_id=admin_session,
        connector_name="google_calendar",
        scopes=("calendar.events",),
    )


async def _complete(
    harness: IntegrationHarness, started: OAuthStart, admin_session: UUID
):
    return await harness.service.complete_oauth(
        context=harness.context,
        admin_session_id=admin_session,
        state=_state(started),
        code=ResolvedSecret(b"fixture-authorization-code"),
    )


async def test_oauth_connect_rotate_revoke_reconnect_and_metadata_only(
    integrations: IntegrationHarness,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    harness = integrations
    admin_session = uuid4()
    started = await _start(harness, admin_session)
    query = parse_qs(urlsplit(started.authorization_url).query)
    assert query["scope"] == ["calendar.events"]
    assert query["code_challenge_method"] == ["S256"]
    connected = await _complete(harness, started, admin_session)
    assert connected.status == "CONNECTED"
    assert connected.health.status == "HEALTHY"
    assert harness.provider.latest_verifier is not None
    assert (
        pkce_challenge(harness.provider.latest_verifier.reveal())
        == query["code_challenge"][0]
    )

    async with session_factory.begin() as session:
        old_ref = await session.scalar(
            text(
                "SELECT credential_secret_id FROM public.integration_connections WHERE id = :id"
            ),
            {"id": connected.id},
        )
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT row_to_json(c)::text FROM public.integration_connections c"
                    )
                )
            )
            .scalars()
            .all()
        )
        audit = (
            (
                await session.execute(
                    text("SELECT payload::text FROM public.audit_events")
                )
            )
            .scalars()
            .all()
        )
        assert "fixture-provider-access-and-refresh" not in repr(
            (rows, audit, connected.model_dump())
        )
        assert "fixture-authorization-code" not in repr((rows, audit))
        assert harness.provider.latest_verifier.reveal().decode() not in repr(
            (rows, audit)
        )
        assert (
            await session.scalar(
                text(
                    "SELECT verifier_secret_id FROM agents_factory_private.integration_oauth_states"
                )
            )
            is None
        )
        assert (
            await session.scalar(text("SELECT count(*) FROM public.secret_envelopes"))
            == 1
        )

    with pytest.raises(IntegrationError, match="could not be completed"):
        await _complete(harness, started, admin_session)
    assert harness.provider.exchange_count == 1
    refreshed = await harness.service.refresh(
        context=harness.context, connection_id=connected.id
    )
    assert refreshed.status == "CONNECTED"
    async with session_factory.begin() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.secret_envelopes WHERE id = :id"),
                {"id": old_ref},
            )
            == 0
        )

    revoked = await harness.service.revoke(
        context=harness.context, connection_id=connected.id
    )
    assert revoked.status == "REVOKED"
    assert harness.provider.revoke_count == 1
    assert (
        await harness.service.revoke(
            context=harness.context, connection_id=connected.id
        )
        == revoked
    )
    assert harness.provider.revoke_count == 1
    with pytest.raises(IntegrationError):
        await harness.service.refresh(
            context=harness.context, connection_id=connected.id
        )
    restarted = await harness.service.start_oauth(
        context=harness.context,
        admin_session_id=admin_session,
        connector_name="google_calendar",
        scopes=("calendar.events",),
        connection_id=connected.id,
    )
    reconnected = await _complete(harness, restarted, admin_session)
    assert reconnected.id == connected.id
    assert reconnected.status == "CONNECTED"


async def test_oauth_tenant_user_session_and_state_binding(
    integrations: IntegrationHarness,
) -> None:
    harness = integrations
    admin_session = uuid4()
    started = await _start(harness, admin_session)
    for context, session_id, value in (
        (harness.other_context, admin_session, _state(started)),
        (replace(harness.context, actor_id=uuid4()), admin_session, _state(started)),
        (harness.context, uuid4(), _state(started)),
        (harness.context, admin_session, "tampered-state-value"),
    ):
        with pytest.raises(IntegrationError) as error:
            await harness.service.complete_oauth(
                context=context,
                admin_session_id=session_id,
                state=value,
                code=ResolvedSecret(b"fixture-authorization-code"),
            )
        assert error.value.code == "integration_oauth_state_invalid"
    assert harness.provider.exchange_count == 0
    assert (await _complete(harness, started, admin_session)).status == "CONNECTED"


async def test_expired_pkce_and_superseded_callbacks_never_reach_provider(
    integrations: IntegrationHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    harness = integrations
    admin_session = uuid4()
    expired = await _start(harness, admin_session)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE agents_factory_private.integration_oauth_states SET created_at = now() - interval '2 hours', expires_at = now() - interval '1 hour' WHERE state_digest = :digest"
            ),
            {"digest": state_digest(_state(expired))},
        )
    with pytest.raises(IntegrationError):
        await _complete(harness, expired, admin_session)
    tampered = await _start(harness, admin_session)
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE agents_factory_private.integration_oauth_states SET code_challenge = :challenge WHERE state_digest = :digest"
            ),
            {"digest": state_digest(_state(tampered)), "challenge": "A" * 43},
        )
    with pytest.raises(IntegrationError):
        await _complete(harness, tampered, admin_session)
    with pytest.raises(IntegrationError):
        await _complete(harness, tampered, admin_session)
    old = await _start(harness, admin_session)
    current = await harness.service.start_oauth(
        context=harness.context,
        admin_session_id=admin_session,
        connector_name="google_calendar",
        scopes=("calendar.events",),
        connection_id=old.connection_id,
    )
    with pytest.raises(IntegrationError):
        await _complete(harness, old, admin_session)
    assert harness.provider.exchange_count == 0
    assert (await _complete(harness, current, admin_session)).status == "CONNECTED"


async def test_provider_failure_commits_consumption_and_sanitized_health(
    integrations: IntegrationHarness, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    harness = integrations
    admin_session = uuid4()
    started = await _start(harness, admin_session)
    harness.provider.failure = RuntimeError("fixture-secret-must-not-leak")
    failed = await _complete(harness, started, admin_session)
    assert failed.status == "REAUTH_REQUIRED"
    assert failed.health.error_code == "provider_unavailable"
    harness.provider.failure = None
    with pytest.raises(IntegrationError):
        await _complete(harness, started, admin_session)
    async with session_factory.begin() as session:
        audit = (
            (
                await session.execute(
                    text("SELECT payload::text FROM public.audit_events")
                )
            )
            .scalars()
            .all()
        )
    assert "fixture-secret-must-not-leak" not in repr((audit, failed))
    assert harness.provider.exchange_count == 1
    harness.provider.granted_scopes = ("calendar.events", "calendar.readonly")
    extra_scopes = await _start(harness, admin_session)
    assert (
        await _complete(harness, extra_scopes, admin_session)
    ).status == "REAUTH_REQUIRED"


async def test_revocation_wins_over_inflight_refresh(
    integrations: IntegrationHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = integrations
    admin_session = uuid4()
    connected = await _complete(
        harness, await _start(harness, admin_session), admin_session
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def held_refresh(credential: ResolvedSecret) -> AuthorizationGrant:
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        return harness.provider._grant()

    monkeypatch.setattr(harness.provider, "refresh", held_refresh)
    refresh = asyncio.create_task(
        harness.service.refresh(context=harness.context, connection_id=connected.id)
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    revoke = asyncio.create_task(
        harness.service.revoke(context=harness.context, connection_id=connected.id)
    )
    release.set()
    refreshed, revoked = await asyncio.wait_for(
        asyncio.gather(refresh, revoke), timeout=10
    )
    assert refreshed.status == "CONNECTED"
    assert revoked.status == "REVOKED"
    assert (await harness.service.list(context=harness.context))[0].status == "REVOKED"
