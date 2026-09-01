import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
from sqlalchemy import text

from apps.backend.tests.integration.integrations.conftest import FakeCredentialProvider
from agents_factory.common.context import TenantContext
from agents_factory.modules.integrations.contracts import (
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.integrations.oauth import ProviderRegistry
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.integrations.woocommerce.auth import WooHTTP, decode
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.usage.models import PriceCard, UnitPrice, UsageConfiguration
from agents_factory.modules.usage.recorder import UsageRecorder


async def test_each_physical_connector_request_is_attributed_and_priced(
    session_factory,
) -> None:
    tenant_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name) "
                "VALUES (:id,:slug,'Connector usage')"
            ),
            {"id": tenant_id, "slug": f"connector-usage-{tenant_id}"},
        )
    providers = ProviderRegistry()
    providers.register("woocommerce", FakeCredentialProvider(oauth=False))
    service = IntegrationService(
        sessions=session_factory,
        key_provider=EnvironmentMasterKeyProvider(
            environment={"APP_MASTER_KEY": "B" * 42 + "A"}
        ),
        providers=providers,
    )
    context = TenantContext(tenant_id, uuid4(), "platform_admin", uuid4())
    product = "woocommerce:orders.get"
    recorder = UsageRecorder(session_factory)
    await recorder.configure(
        context=context,
        configuration=UsageConfiguration(
            prices=(
                PriceCard(
                    id=uuid4(),
                    provider="woocommerce",
                    product=product,
                    kind="tool",
                    currency="USD",
                    effective_from=datetime.now(UTC) - timedelta(minutes=1),
                    rates={"requests": UnitPrice(amount=Decimal("0.01"))},
                ),
            )
        ),
        expected_revision=0,
    )
    credential = ResolvedSecret(
        json.dumps(
            {
                "store_url": "https://shop.example.test",
                "consumer_key": "fixture-key-123",
                "consumer_secret": "fixture-secret-123",
                "permission": "read",
            }
        ).encode()
    )
    connection = await service.connect_api_key(
        context=context,
        connector_name="woocommerce",
        credential=credential,
    )
    provider_calls = 0

    def provider(_: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={"id": provider_calls})

    http = WooHTTP(
        ("https://shop.example.test",),
        transport=httpx.MockTransport(provider),
        resolver=lambda _: _public_address(),
    )

    class TwoPageConnector:
        def __init__(self, leased_credential: ResolvedSecret) -> None:
            self.credential = leased_credential

        async def execute(self, request: ConnectorRequest) -> ConnectorResult:
            saved = decode(self.credential)
            await http.json(saved, "GET", "orders/1")
            await http.json(saved, "GET", "orders/2")
            return ConnectorResult(operation=request.operation, status="SUCCEEDED")

    worker = replace(context, actor_type="system")
    result = await service.execute_connector(
        context=worker,
        connection_id=connection.id,
        connector_name="woocommerce",
        request=ConnectorRequest(
            tenant_id=worker.tenant_id,
            binding_id=uuid4(),
            operation="orders.get",
            arguments={},
        ),
        build=TwoPageConnector,
    )

    assert result.status == "SUCCEEDED" and provider_calls == 2
    async with session_factory.begin() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT event,quote FROM public.usage_records "
                        "WHERE tenant_id=:tenant AND provider='woocommerce' "
                        "ORDER BY source_key"
                    ),
                    {"tenant": worker.tenant_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 2
    assert all(row["event"]["product"] == product for row in rows)
    assert all(row["event"]["measurements"]["requests"] == 1 for row in rows)
    assert all(row["event"]["measurements"]["tool_calls"] is None for row in rows)
    assert all(Decimal(row["quote"]["amount"]) == Decimal("0.01") for row in rows)


async def _public_address() -> tuple[str, ...]:
    return ("93.184.216.34",)
