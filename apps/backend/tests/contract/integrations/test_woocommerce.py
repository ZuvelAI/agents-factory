from __future__ import annotations

import logging
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from apps.backend.tests.order_support import (
    WooFixture,
    STORE,
    CUSTOMER,
    ADDRESS,
    woo_credential,
    public_dns,
)
from apps.backend.tests.contract.integrations.google.test_google_contracts import (
    request,
)
from agents_factory.modules.integrations.orders import (
    READS,
    WRITES,
    CustomerMatch,
    OrderFailure,
)
from agents_factory.modules.integrations.woocommerce.auth import (
    WooCredentialProvider,
    WooHTTP,
    decode,
    validate_store_url,
)
from agents_factory.modules.integrations.woocommerce.client import WooCommerceConnector
from agents_factory.modules.secrets.envelope import (
    EnvironmentMasterKeyProvider,
    SecretEnvelopeCipher,
)
from agents_factory.modules.secrets.contracts import SecretAccessDenied


async def test_woo_reads_customer_matching_pagination_and_tracking_absence() -> None:
    fixture = WooFixture()
    for operation in READS:
        args = {"customer": CUSTOMER, "order_id": "42"}
        result = await fixture.adapter.execute(
            request(fixture.binding, operation, args)
        )
        assert result.status == "SUCCEEDED"
        assert "billing" not in result.data and "customer_id" not in result.data
        if operation == READS[2]:
            assert result.data["tracking_available"] is False
        if operation == READS[1]:
            assert result.data["status"] == "PROCESSING"
    found = await fixture.adapter.execute(
        request(fixture.binding, READS[0], {"customer": CUSTOMER, "limit": 1})
    )
    assert (
        found.data["next_page"] == 2 and fixture.calls[-1].url.params["customer"] == "7"
    )
    denied = await fixture.adapter.execute(
        request(
            fixture.binding,
            READS[1],
            {"customer": {"customer_id": "9"}, "order_id": "42"},
        )
    )
    assert denied.error_code == "order_not_found" and not denied.data
    fixture.order["status"] = "custom-unknown"
    unknown = await fixture.adapter.execute(
        request(fixture.binding, READS[1], {"customer": CUSTOMER, "order_id": "42"})
    )
    assert unknown.data["status"] == "UNKNOWN"
    with pytest.raises(ValidationError):
        CustomerMatch(customer_id="0")


async def test_woo_all_writes_receipts_conflict_and_cancellation_request_only() -> None:
    fixture = WooFixture()
    for operation, changes in zip(
        WRITES,
        (
            {"address": ADDRESS},
            {"contact": {"phone": "+571111111111"}},
            {"note": "Customer called"},
            {"reason": "Customer request"},
        ),
    ):
        read = await fixture.adapter.execute(
            request(fixture.binding, READS[1], {"customer": CUSTOMER, "order_id": "42"})
        )
        args = {
            "customer": CUSTOMER,
            "order_id": "42",
            "expected_version": read.data["version"],
            **changes,
        }
        command = request(fixture.binding, operation, args, key=operation)
        result = await fixture.adapter.execute(command)
        assert result.status == "SUCCEEDED", result
        replay = await fixture.adapter.execute(command)
        assert replay.status == "SUCCEEDED" and replay.data["replayed"] is True
    assert len(fixture.notes) == 1
    assert sum(req.method == "PUT" for req in fixture.calls) == 3
    assert result.data["cancellation_executed"] is False
    assert fixture.order["status"] == "processing"
    stale = await fixture.adapter.execute(
        request(
            fixture.binding,
            WRITES[0],
            {
                "customer": CUSTOMER,
                "order_id": "42",
                "expected_version": "0" * 64,
                "address": ADDRESS,
            },
            key="stale",
        )
    )
    assert stale.error_code == "stale_version"
    fixture.order["meta_data"].append({"key": "tracking_number", "value": "SHIPPED-1"})
    read = await fixture.adapter.execute(
        request(fixture.binding, READS[1], {"customer": CUSTOMER, "order_id": "42"})
    )
    denied = await fixture.adapter.execute(
        request(
            fixture.binding,
            WRITES[3],
            {
                "customer": CUSTOMER,
                "order_id": "42",
                "expected_version": read.data["version"],
                "reason": "Too late",
            },
            key="shipped",
        )
    )
    assert denied.error_code == "order_not_mutable"


async def test_woo_transport_scope_ssrf_redaction_uncertainty_and_encrypted_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fixture = WooFixture()
    plain = woo_credential().reveal()
    cipher = SecretEnvelopeCipher(
        EnvironmentMasterKeyProvider(environment={"APP_MASTER_KEY": "B" * 42 + "A"})
    )
    tenant = fixture.binding.tenant_id
    envelope = cipher.encrypt(
        secret_id=uuid4(),
        tenant_id=tenant,
        purpose="integrations.credentials",
        record_context="woocommerce:fixture",
        plaintext=plain,
    )
    assert plain not in envelope.ciphertext
    assert (
        cipher.decrypt(
            envelope,
            tenant_id=tenant,
            purpose="integrations.credentials",
            record_context="woocommerce:fixture",
        )
        == plain
    )
    with pytest.raises(SecretAccessDenied):
        cipher.decrypt(
            envelope,
            tenant_id=uuid4(),
            purpose="integrations.credentials",
            record_context="woocommerce:fixture",
        )
    with caplog.at_level(logging.DEBUG):
        await WooCredentialProvider(fixture.http).check_health(woo_credential())
        read = await fixture.adapter.execute(
            request(fixture.binding, READS[1], {"customer": CUSTOMER, "order_id": "42"})
        )
        fixture.fail_write = True
        failed = await fixture.adapter.execute(
            request(
                fixture.binding,
                WRITES[0],
                {
                    "customer": CUSTOMER,
                    "order_id": "42",
                    "expected_version": read.data["version"],
                    "address": ADDRESS,
                },
            )
        )
        assert (
            failed.status == "UNCERTAIN" and failed.error_code == "provider_unavailable"
        )
    assert (
        "fixture-consumer" not in caplog.text
        and "private-provider-error" not in caplog.text
    )
    readonly = WooCommerceConnector(
        binding=fixture.binding,
        resource=fixture.resource,
        credential=woo_credential("read"),
        http=fixture.http,
    )
    denied = await readonly.execute(
        request(
            fixture.binding,
            WRITES[0],
            {
                "customer": CUSTOMER,
                "order_id": "42",
                "expected_version": read.data["version"],
                "address": ADDRESS,
            },
        )
    )
    assert denied.error_code == "permission_denied"
    assert "fixture-consumer" not in repr(decode(woo_credential()))
    for url in (
        "http://store.example.test",
        STORE + "/../admin",
        STORE + "?key=x",
        "https://user:pass@store.example.test",
    ):
        with pytest.raises(ValueError):
            validate_store_url(url)

    async def private_dns(host: str) -> tuple[str, ...]:
        return ("127.0.0.1",)

    unsafe = WooHTTP(
        (STORE,),
        resolver=private_dns,
        transport=httpx.MockTransport(lambda _: pytest.fail("private IP contacted")),
    )
    with pytest.raises(OrderFailure, match="store_not_allowed"):
        await unsafe.json(decode(woo_credential()), "GET", "orders")
    redirect = WooHTTP(
        (STORE,),
        resolver=public_dns,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                302, headers={"Location": "https://attacker.example.test"}
            )
        ),
    )
    with pytest.raises(OrderFailure, match="provider_rejected"):
        await redirect.json(decode(woo_credential()), "GET", "orders")
