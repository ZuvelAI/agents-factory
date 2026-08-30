from __future__ import annotations

import json
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.google.auth import (
    CALENDAR_READ,
    GMAIL_SEND,
    GoogleClientConfiguration,
    GoogleOAuthProvider,
    GoogleProduct,
)
from agents_factory.modules.integrations.google.base import GoogleBinding, GoogleHTTP
from agents_factory.modules.integrations.google.calendar import CalendarResource
from agents_factory.modules.integrations.google.factory import ConnectedGoogleConnector
from agents_factory.modules.integrations.models import IntegrationError
from agents_factory.modules.integrations.oauth import ProviderRegistry
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret

from .conftest import IntegrationHarness


async def test_google_vault_execution_refresh_audit_and_independent_health(
    integrations: IntegrationHarness,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One integrated scenario; Google is fake, tenant/vault/audit boundaries are real."""
    revoked: set[str] = set()
    scopes = {"google_calendar": CALENDAR_READ, "gmail": GMAIL_SEND}
    refresh_count = 0
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal refresh_count
        calls.append(req.url.path)
        if req.url.path.endswith("/token"):
            form = parse_qs(req.content.decode())
            product = form["client_id"][0]
            if form["grant_type"] == ["refresh_token"]:
                refresh_count += 1
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-access-" + product,
                    "refresh_token": "fixture-refresh-" + product,
                    "scope": scopes[product],
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        if req.url.path.endswith("tokeninfo"):
            product = req.url.params["access_token"].removeprefix("fixture-access-")
            if product in revoked:
                return httpx.Response(400, json={"error": "invalid_token"})
            return httpx.Response(
                200,
                json={
                    "scope": scopes[product],
                    "issued_to": product,
                    "expires_in": 3600,
                },
            )
        if req.url.path.endswith("revoke"):
            revoked.add(
                parse_qs(req.content.decode())["token"][0].removeprefix(
                    "fixture-refresh-"
                )
            )
            return httpx.Response(200)
        assert req.headers["Authorization"] == "Bearer fixture-access-google_calendar"
        assert "google_calendar" not in revoked
        return httpx.Response(200, json={"id": "eventfixture01", "etag": '"v1"'})

    transport = GoogleHTTP(httpx.MockTransport(handler))
    registry = ProviderRegistry()
    products: tuple[GoogleProduct, ...] = ("google_calendar", "gmail")
    for product in products:
        registry.register(
            product,
            GoogleOAuthProvider(
                product=product,
                configuration=GoogleClientConfiguration.model_validate(
                    {
                        "client_id": product,
                        "client_secret": "fixture-client-credential",
                        "redirect_uri": "https://control.example.test/callback",
                    }
                ),
                http=transport,
            ),
        )
    service = IntegrationService(
        sessions=session_factory,
        key_provider=EnvironmentMasterKeyProvider(
            environment={"APP_MASTER_KEY": "B" * 42 + "A"}
        ),
        providers=registry,
    )
    context = integrations.context
    connections = {}
    for product in products:
        admin_session = uuid4()
        start = await service.start_oauth(
            context=context,
            admin_session_id=admin_session,
            connector_name=product,
            scopes=(scopes[product],),
        )
        params = parse_qs(urlsplit(start.authorization_url).query)
        assert params["scope"] == [scopes[product]]
        connected = await service.complete_oauth(
            context=context,
            admin_session_id=admin_session,
            state=params["state"][0],
            code=ResolvedSecret(b"fixture-authorization-code"),
        )
        assert connected.status == "CONNECTED" and connected.granted_scopes == (
            scopes[product],
        )
        assert (
            await service.check_health(context=context, connection_id=connected.id)
        ).health.status == "HEALTHY"
        connections[product] = connected

    # The new execution boundary renews near-expiry credentials under the same
    # row lock as revoke, and stores the rotated SecretRef before provider use.
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "UPDATE public.integration_connections SET expires_at = now() + interval '1 second' WHERE id = :id"
            ),
            {"id": connections["google_calendar"].id},
        )
    # Identify the backend job/action actor; the vault never accepts anonymous use.
    worker = replace(context, actor_type="system", actor_id=uuid4())
    bound = GoogleBinding(context.tenant_id, uuid4(), frozenset({"calendar.get_event"}))
    adapter = ConnectedGoogleConnector(
        service=service,
        context=worker,
        connection_id=connections["google_calendar"].id,
        product="google_calendar",
        binding=bound,
        resource=CalendarResource(calendar_id="primary"),
        http=transport,
    )
    request = ConnectorRequest(
        tenant_id=context.tenant_id,
        binding_id=bound.binding_id,
        operation="calendar.get_event",
        arguments={"event_id": "eventfixture01"},
    )
    assert (await adapter.execute(request)).status == "SUCCEEDED"
    assert refresh_count == 1
    assert (
        await service.revoke(context=context, connection_id=connections["gmail"].id)
    ).status == "REVOKED"
    assert (
        await service.check_health(
            context=context, connection_id=connections["google_calendar"].id
        )
    ).health.status == "HEALTHY"
    assert (await adapter.execute(request)).status == "SUCCEEDED"

    before = len(calls)
    wrong_tenant = replace(adapter, context=integrations.other_context)
    assert (await wrong_tenant.execute(request)).error_code == "tenant_mismatch"
    customer = replace(adapter, context=replace(context, actor_type="customer"))
    with pytest.raises(IntegrationError, match="integration"):
        await customer.execute(request)
    disabled = replace(adapter, connection_id=connections["gmail"].id)
    assert (await disabled.execute(request)).error_code == "integration_not_connected"
    assert len(calls) == before
    async with session_factory.begin() as session:
        payloads = (
            (
                await session.execute(
                    text(
                        "SELECT payload FROM public.audit_events WHERE tenant_id = :tenant AND event_type = 'integration.operation'"
                    ),
                    {"tenant": context.tenant_id},
                )
            )
            .scalars()
            .all()
        )
    assert len(payloads) == 2
    assert all(payload["status"] == "SUCCEEDED" for payload in payloads)
    serialized = json.dumps(payloads)
    assert (
        "fixture-access" not in serialized
        and "fixture-refresh" not in serialized
        and "eventfixture01" not in serialized
    )
