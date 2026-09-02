from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from starlette.requests import Request

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal
from agents_factory.modules.integrations.meta_bridge import MetaConnectionBridge
from agents_factory.modules.integrations.oauth import ProviderRegistry
from agents_factory.modules.integrations.registry import V1_CONNECTOR_CATALOG
from agents_factory.modules.integrations import router as catalog_router
from agents_factory.modules.whatsapp.account_service import (
    WhatsAppAccountService,
    WhatsAppAccountSummary,
)


async def test_catalog_reuses_meta_accounts_without_enabling_unimplemented_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = TenantContext(uuid4(), uuid4(), "platform_admin", uuid4())
    account = WhatsAppAccountSummary(
        id=uuid4(),
        business_id="fixture-business",
        waba_id="fixture-waba",
        phone_number_id="fixture-phone",
        status="active",
        mode="API_ONLY",
        coexistence_eligibility="UNKNOWN",
        granted_scopes=("whatsapp_business_management", "whatsapp_business_messaging"),
        health_status="HEALTHY",
        last_health_checked_at=None,
        token_expires_at=None,
        verified_at=None,
    )
    accounts = Mock(spec=WhatsAppAccountService)
    accounts.list_summaries = AsyncMock(return_value=(account,))
    accounts.check_health = AsyncMock(return_value=account)
    accounts.revoke = AsyncMock(return_value=account)
    bridge = MetaConnectionBridge(accounts)
    projected = await bridge.list(context)
    assert projected[0].id == account.id
    assert projected[0].auth_kind == "META_EMBEDDED"
    assert "secret_ref" not in projected[0].model_dump_json()
    await bridge.check_health(context, account.id)
    await bridge.revoke(context, account.id)
    accounts.check_health.assert_awaited_once()
    accounts.revoke.assert_awaited_once()

    monkeypatch.setattr(
        catalog_router, "list_connections", AsyncMock(return_value=projected)
    )
    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(
                state=SimpleNamespace(integration_providers=ProviderRegistry())
            ),
        }
    )
    catalog = await catalog_router.integration_catalog(
        context.tenant_id, request, AdminPrincipal(uuid4(), uuid4()), Mock()
    )
    entries = {entry.connector_name: entry for entry in catalog}
    assert entries["meta_whatsapp"].connections == projected
    for name in (
        "google_calendar",
        "gmail",
        "google_drive",
        "google_sheets",
        "woocommerce",
    ):
        assert not entries[name].available
        assert entries[name].availability == "SETUP_REQUIRED"
        assert (
            entries[name].supported_operations
            == V1_CONNECTOR_CATALOG.get(name, "1.0.0").supported_operations
        )
    assert not entries["generic_rest_api"].available
    assert entries["generic_rest_api"].availability == "COMING_LATER"
    assert entries["generic_rest_api"].supported_operations == ()
