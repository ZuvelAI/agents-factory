from __future__ import annotations

import copy
import json
import re
from urllib.parse import unquote
from uuid import uuid4

import httpx

from agents_factory.modules.integrations.google.base import GoogleBinding, GoogleHTTP
from agents_factory.modules.integrations.google.orders_sheet import (
    OrdersSheetResource,
    OrdersSheetConnector,
)
from agents_factory.modules.integrations.orders import OPERATIONS, WRITES
from agents_factory.modules.integrations.woocommerce.auth import WooHTTP
from agents_factory.modules.integrations.woocommerce.client import (
    WooCommerceConnector,
    WooResource,
)
from agents_factory.modules.secrets.redaction import ResolvedSecret
from apps.backend.tests.contract.integrations.google.test_google_contracts import (
    credential,
)
from agents_factory.modules.integrations.google.auth import SHEETS_WRITE


STORE = "https://store.example.test"
CUSTOMER = {"customer_id": "7"}
ADDRESS = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "address_1": "Calle 1",
    "city": "Bogota",
    "postcode": "110111",
    "country": "CO",
}


def woo_credential(permission: str = "read_write") -> ResolvedSecret:
    return ResolvedSecret(
        json.dumps(
            {
                "store_url": STORE,
                "consumer_key": "fixture-consumer-key",
                "consumer_secret": "fixture-consumer-secret",
                "permission": permission,
            }
        ).encode()
    )


async def public_dns(host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


class WooFixture:
    def __init__(self) -> None:
        self.order = {
            "id": 42,
            "customer_id": 7,
            "status": "processing",
            "billing": {"email": "ada@example.test", "phone": "+571234567890"},
            "shipping": dict(ADDRESS),
            "line_items": [{"id": 1, "name": "Item", "sku": "SKU1", "quantity": 2}],
            "meta_data": [],
            "date_modified_gmt": "2026-08-30T12:00:00",
        }
        self.notes: list[dict[str, object]] = []
        self.calls: list[httpx.Request] = []
        self.fail_write = False
        self.binding = GoogleBinding(uuid4(), uuid4(), frozenset(OPERATIONS))
        self.resource = WooResource(
            store_url=STORE,
            writable_operations=frozenset(WRITES),
            tracking_number_meta="tracking_number",
        )
        self.http = WooHTTP(
            (STORE,), transport=httpx.MockTransport(self.handle), resolver=public_dns
        )
        self.adapter = WooCommerceConnector(
            binding=self.binding,
            resource=self.resource,
            credential=woo_credential(),
            http=self.http,
        )

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        assert (
            req.url.host == "93.184.216.34"
            and req.headers["Host"] == "store.example.test"
        )
        assert req.extensions["sni_hostname"] == "store.example.test"
        assert req.headers["Authorization"].startswith(
            "Basic "
        ) and "consumer_secret" not in str(req.url)
        if req.method != "GET" and self.fail_write:
            raise httpx.ReadTimeout("fixture-private-provider-error")
        if req.url.path.endswith("/notes"):
            if req.method == "GET":
                return httpx.Response(200, json=copy.deepcopy(self.notes))
            payload = json.loads(req.content)
            assert payload["customer_note"] is False
            note = {"id": len(self.notes) + 1, **payload}
            self.notes.append(note)
            return httpx.Response(201, json=note)
        if req.url.path.endswith("/orders"):
            return httpx.Response(200, json=[copy.deepcopy(self.order)])
        if req.method == "PUT":
            payload = json.loads(req.content)
            assert "status" not in payload and "refunds" not in payload
            for field in ("shipping", "billing"):
                if field in payload:
                    self.order[field].update(payload[field])
            self.order["meta_data"].extend(payload["meta_data"])
        return httpx.Response(200, json=copy.deepcopy(self.order))


class SheetFixture:
    def __init__(
        self,
        *,
        writable: bool = True,
        max_rows: int = 20,
        scopes: tuple[str, ...] = (SHEETS_WRITE,),
    ) -> None:
        fields = (
            "order_id",
            "customer_id",
            "status",
            "email",
            "tracking",
            "items",
            "shipping_address",
            "contact_information",
            "notes",
            "cancellation_request",
            "action_receipts",
        )
        self.resource = OrdersSheetResource(
            spreadsheet_id="fixture-sheet",
            tab="Orders",
            headers=tuple(fields),
            fields={name: name for name in fields},
            max_rows=max_rows,
            writable_fields=frozenset(
                {
                    "shipping_address",
                    "contact_information",
                    "notes",
                    "cancellation_request",
                    "action_receipts",
                }
            )
            if writable
            else frozenset(),
        )
        self.binding = GoogleBinding(
            uuid4(), uuid4(), frozenset(self.resource.supported_operations)
        )
        self.rows: dict[int, list[object]] = {
            2: [
                "42",
                "7",
                "processing",
                "ada@example.test",
                "",
                json.dumps(
                    [{"item_id": "1", "name": "Item", "sku": "SKU1", "quantity": 2}]
                ),
                json.dumps(ADDRESS),
                "{}",
                "[]",
                "{}",
                "{}",
            ]
        }
        self.calls: list[httpx.Request] = []
        self.writes = 0
        self.conflict = False
        self.fail_write = False
        self.bad_headers = False
        self.http = GoogleHTTP(httpx.MockTransport(self.handle))
        self.adapter = OrdersSheetConnector(
            binding=self.binding,
            resource=self.resource,
            credential=credential(scopes),
            http=self.http,
        )

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if req.method == "POST":
            if self.fail_write:
                raise httpx.ReadTimeout("private-sheet-detail")
            payload = json.loads(req.content)
            assert payload["valueInputOption"] == "RAW"
            self.writes += 1
            for entry in payload["data"]:
                match = re.search(r"!([A-Z])(\d+)$", entry["range"])
                assert match
                self.rows[int(match[2])][ord(match[1]) - 65] = entry["values"][0][0]
            return httpx.Response(200, json={"totalUpdatedCells": len(payload["data"])})
        match = re.search(r"!A(\d+):[A-Z](\d+)$", unquote(req.url.path))
        assert match
        start, end = int(match[1]), int(match[2])
        if start == end == 1:
            return httpx.Response(
                200,
                json={
                    "values": [
                        ["wrong"] if self.bad_headers else list(self.resource.headers)
                    ]
                },
            )
        if start == end and self.conflict:
            self.rows[start][2] = "completed"
        last = max(
            (index for index in self.rows if start <= index <= end), default=start - 1
        )
        return httpx.Response(
            200,
            json={
                "values": [
                    copy.deepcopy(self.rows.get(index, []))
                    for index in range(start, last + 1)
                ]
            },
        )
