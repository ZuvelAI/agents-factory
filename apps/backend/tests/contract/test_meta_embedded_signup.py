from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import httpx
from pydantic import SecretStr

from agents_factory.common.context import TenantContext
from agents_factory.modules.secrets.contracts import SecretRef
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.whatsapp.account_service import (
    WhatsAppAccountService,
    WhatsAppAccountSummary,
)
from agents_factory.modules.whatsapp.contracts import MetaAuthorizationSnapshot
from agents_factory.modules.whatsapp.meta_provider import MetaEmbeddedSignupClient
from agents_factory.modules.whatsapp.signup_service import (
    REQUIRED_META_SCOPES,
    ConnectedWhatsAppAccount,
    WhatsAppSignupError,
    WhatsAppSignupService,
)


TENANT_ID = UUID("019c2000-0000-7000-8000-000000000101")
OTHER_TENANT_ID = UUID("019c2000-0000-7000-8000-000000000102")
ADMIN_ID = UUID("019c2000-0000-7000-8000-000000000103")
SESSION_ID = UUID("019c2000-0000-7000-8000-000000000104")
ACCOUNT_ID = UUID("019c2000-0000-7000-8000-000000000105")
SECRET_ID = UUID("019c2000-0000-7000-8000-000000000106")
NOW = datetime(2026, 8, 28, 15, 0, tzinfo=UTC)


def context(tenant_id: UUID = TENANT_ID) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=ADMIN_ID,
        actor_type="platform_admin",
        correlation_id=UUID("019c2000-0000-7000-8000-000000000107"),
    )


def snapshot(
    *,
    scopes: frozenset[str] = REQUIRED_META_SCOPES,
    owns_waba: bool = True,
    owns_phone_number: bool = True,
    eligibility: str = "UNKNOWN",
) -> MetaAuthorizationSnapshot:
    return MetaAuthorizationSnapshot(
        access_token=ResolvedSecret(b"client-owned-meta-token"),
        business_id="business-client-1",
        waba_id="waba-client-1",
        phone_number_id="phone-client-1",
        granted_scopes=scopes,
        token_expires_at=None,
        owns_waba=owns_waba,
        owns_phone_number=owns_phone_number,
        coexistence_eligibility=eligibility,  # type: ignore[arg-type]
    )


def account(*, tenant_id: UUID = TENANT_ID) -> ConnectedWhatsAppAccount:
    return ConnectedWhatsAppAccount(
        id=ACCOUNT_ID,
        tenant_id=tenant_id,
        business_id="business-client-1",
        waba_id="waba-client-1",
        phone_number_id="phone-client-1",
        status="active",
        mode="API_ONLY",
        coexistence_eligibility="UNKNOWN",
        granted_scopes=tuple(sorted(REQUIRED_META_SCOPES)),
        health_status="HEALTHY",
        last_health_checked_at=NOW,
        token_expires_at=None,
        verified_at=NOW,
        access_token_secret_ref=SecretRef(SECRET_ID),
    )


def service(
    *,
    authorization: MetaAuthorizationSnapshot | Exception | None = None,
    existing: ConnectedWhatsAppAccount | None = None,
    state_consumed: bool = True,
) -> tuple[WhatsAppSignupService, AsyncMock, AsyncMock, AsyncMock]:
    repository = AsyncMock()
    repository.consume_signup_state.return_value = state_consumed
    repository.find_by_phone_number.return_value = existing
    repository.connect_account.return_value = account()
    provider = AsyncMock()
    if isinstance(authorization, Exception):
        provider.exchange_and_verify.side_effect = authorization
    else:
        provider.exchange_and_verify.return_value = authorization or snapshot()
    vault = AsyncMock()
    vault.store.return_value = SecretRef(SECRET_ID)
    return (
        WhatsAppSignupService(
            repository=repository,
            vault=vault,
            provider=provider,
            now=lambda: NOW,
        ),
        repository,
        provider,
        vault,
    )


@pytest.mark.asyncio
async def test_signup_is_one_time_client_owned_and_api_only_by_default() -> None:
    signup, repository, provider, vault = service()

    started = await signup.start(context=context(), admin_session_id=SESSION_ID)
    connected = await signup.complete(
        context=context(),
        admin_session_id=SESSION_ID,
        state=started.state,
        code="single-use-authorization-code",
        business_id="business-client-1",
        waba_id="waba-client-1",
        phone_number_id="phone-client-1",
    )

    saved = repository.save_signup_state.await_args.kwargs
    assert saved["state_digest"] != started.state
    assert "client-owned-meta-token" not in repr(saved)
    provider.exchange_and_verify.assert_awaited_once_with(
        code="single-use-authorization-code",
        business_id="business-client-1",
        waba_id="waba-client-1",
        phone_number_id="phone-client-1",
    )
    stored_secret = vault.store.await_args.kwargs
    connected_account = repository.connect_account.await_args.kwargs
    repository.lock_phone_number.assert_awaited_once_with(
        phone_number_id="phone-client-1"
    )
    assert stored_secret == {
        "context": context(),
        "purpose": "whatsapp.meta_access_token",
        "record_context": (f"whatsapp_account:{connected_account['account_id']}"),
        "plaintext": b"client-owned-meta-token",
    }
    assert connected.mode == "API_ONLY"
    assert connected.access_token_secret_ref == SecretRef(SECRET_ID)
    assert "client-owned-meta-token" not in repr(connected)
    summary = WhatsAppAccountSummary.from_account(connected)
    assert "access_token" not in summary.__dataclass_fields__
    assert "access_token_secret_ref" not in summary.__dataclass_fields__


@pytest.mark.asyncio
async def test_signup_rejects_expired_replayed_or_wrong_tenant_session_state() -> None:
    signup, repository, provider, vault = service(state_consumed=False)

    with pytest.raises(WhatsAppSignupError, match="authorization session") as error:
        await signup.complete(
            context=context(OTHER_TENANT_ID),
            admin_session_id=SESSION_ID,
            state="invalid-or-replayed-state",
            code="code",
            business_id="business-client-1",
            waba_id="waba-client-1",
            phone_number_id="phone-client-1",
        )

    assert error.value.code == "whatsapp_signup_state_invalid"
    provider.exchange_and_verify.assert_not_awaited()
    vault.store.assert_not_awaited()
    repository.connect_account.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authorization", "expected_code"),
    [
        (snapshot(owns_waba=False), "meta_asset_ownership_invalid"),
        (snapshot(owns_phone_number=False), "meta_asset_ownership_invalid"),
        (
            snapshot(scopes=frozenset({"whatsapp_business_messaging"})),
            "meta_scopes_missing",
        ),
        (RuntimeError("revoked provider token"), "meta_authorization_failed"),
    ],
)
async def test_signup_rejects_untrusted_meta_authorization(
    authorization: MetaAuthorizationSnapshot | Exception,
    expected_code: str,
) -> None:
    signup, repository, _provider, vault = service(authorization=authorization)

    with pytest.raises(WhatsAppSignupError) as error:
        await signup.complete(
            context=context(),
            admin_session_id=SESSION_ID,
            state="valid-state",
            code="code",
            business_id="business-client-1",
            waba_id="waba-client-1",
            phone_number_id="phone-client-1",
        )

    assert error.value.code == expected_code
    vault.store.assert_not_awaited()
    repository.connect_account.assert_not_awaited()


@pytest.mark.asyncio
async def test_phone_mapping_cannot_cross_tenants() -> None:
    signup, repository, _provider, vault = service(
        existing=account(tenant_id=OTHER_TENANT_ID)
    )

    with pytest.raises(WhatsAppSignupError) as error:
        await signup.complete(
            context=context(),
            admin_session_id=SESSION_ID,
            state="valid-state",
            code="code",
            business_id="business-client-1",
            waba_id="waba-client-1",
            phone_number_id="phone-client-1",
        )

    assert error.value.code == "whatsapp_phone_already_connected"
    vault.store.assert_not_awaited()
    repository.connect_account.assert_not_awaited()


@pytest.mark.asyncio
async def test_coexistence_requires_explicit_provider_eligibility() -> None:
    signup, repository, _provider, vault = service(
        authorization=snapshot(eligibility="UNKNOWN")
    )

    with pytest.raises(WhatsAppSignupError) as error:
        await signup.complete(
            context=context(),
            admin_session_id=SESSION_ID,
            state="valid-state",
            code="code",
            business_id="business-client-1",
            waba_id="waba-client-1",
            phone_number_id="phone-client-1",
            requested_mode="COEXISTENCE",
        )

    assert error.value.code == "whatsapp_coexistence_ineligible"
    vault.store.assert_not_awaited()
    repository.connect_account.assert_not_awaited()


@pytest.mark.asyncio
async def test_concrete_meta_client_verifies_app_business_waba_and_phone() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "verified-token"})
        if path.endswith("/debug_token"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "is_valid": True,
                        "app_id": "meta-app-1",
                        "scopes": sorted(REQUIRED_META_SCOPES),
                        "granular_scopes": [
                            {
                                "scope": "whatsapp_business_management",
                                "target_ids": ["waba-client-1"],
                            }
                        ],
                    }
                },
            )
        if path.endswith("/business-client-1/owned_whatsapp_business_accounts"):
            return httpx.Response(200, json={"data": [{"id": "waba-client-1"}]})
        if path.endswith("/waba-client-1/phone_numbers"):
            return httpx.Response(200, json={"data": [{"id": "phone-client-1"}]})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        authorization = await MetaEmbeddedSignupClient(
            app_id="meta-app-1",
            app_secret=SecretStr("meta-app-secret"),
            redirect_uri="https://control.example.test/meta/callback",
            graph_api_base_url="https://graph.facebook.com/v25.0",
            http_client=client,
        ).exchange_and_verify(
            code="one-time-code",
            business_id="business-client-1",
            waba_id="waba-client-1",
            phone_number_id="phone-client-1",
        )

    assert authorization.owns_waba is True
    assert authorization.owns_phone_number is True
    assert authorization.business_id == "business-client-1"
    assert "verified-token" not in repr(authorization)


@pytest.mark.asyncio
async def test_revoke_fails_closed_locally_when_meta_is_unavailable() -> None:
    active = account()
    inactive = replace(active, status="inactive", health_status="REAUTH_REQUIRED")
    repository = AsyncMock()
    repository.get.return_value = active
    repository.deactivate.return_value = inactive
    repository.update_health.return_value = inactive
    vault = AsyncMock()
    vault.load.return_value = ResolvedSecret(b"client-owned-meta-token")
    provider = AsyncMock()
    provider.revoke.side_effect = httpx.ConnectError("Meta unavailable")
    accounts = WhatsAppAccountService(
        repository=repository,
        vault=vault,
        provider=provider,
    )

    summary = await accounts.revoke(
        context=context(), account_id=ACCOUNT_ID, revoked_at=NOW
    )

    assert summary.status == "inactive"
    repository.deactivate.assert_awaited_once()
    repository.update_health.assert_awaited_once_with(
        context=context(),
        account_id=ACCOUNT_ID,
        status="REAUTH_REQUIRED",
        error_code="meta_revoke_pending",
        checked_at=NOW,
    )
    vault.delete.assert_not_awaited()
