from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, ValidationError, field_validator, model_validator

from agents_factory.common.context import TenantContext
from agents_factory.modules.integrations.contracts import (
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.integrations.google.base import GoogleBinding, InputModel
from agents_factory.modules.integrations.orders import (
    INPUTS,
    READS,
    WRITES,
    STATUS_MAP,
    AddNote,
    CancelRequest,
    ContactUpdate,
    FindOrder,
    OrderFailure,
    OrderItem,
    OrderRead,
    OrderSnapshot,
    OrderWrite,
    ShippingUpdate,
    Status,
    action_marker,
    assert_owner,
    digest,
    write_precondition,
    write_result,
)
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.integrations.woocommerce.auth import (
    WooHTTP,
    decode,
    validate_store_url,
)
from agents_factory.modules.integrations.woocommerce.manifest import (
    WOOCOMMERCE_MANIFEST,
)
from agents_factory.modules.secrets.redaction import ResolvedSecret


class WooResource(InputModel):
    store_url: str
    writable_operations: frozenset[str] = frozenset()
    status_mapping: dict[str, Status] = Field(default_factory=lambda: dict(STATUS_MAP))
    tracking_number_meta: str | None = Field(default=None, min_length=1, max_length=100)
    tracking_url_meta: str | None = Field(default=None, min_length=1, max_length=100)

    _url = field_validator("store_url")(validate_store_url)

    @model_validator(mode="after")
    def writes(self) -> Self:
        if not self.writable_operations.issubset(WRITES):
            raise ValueError("unsupported WooCommerce write")
        return self

    @property
    def supported_operations(self) -> tuple[str, ...]:
        return READS + tuple(op for op in WRITES if op in self.writable_operations)


def metadata(order: dict[str, object]) -> dict[str, object]:
    values = order.get("meta_data", [])
    if not isinstance(values, list):
        raise OrderFailure("invalid_response")
    result: dict[str, object] = {}
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise OrderFailure("invalid_response")
        if item["key"] in result:
            raise OrderFailure("ambiguous_metadata")
        result[item["key"]] = item.get("value")
    return result


def record(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OrderFailure("invalid_response")
    return value


def strings(value: object, fields: tuple[str, ...]) -> dict[str, str]:
    obj = record(value)
    return {key: value for key in fields if isinstance(value := obj.get(key), str)}


def normalize(value: dict[str, object], resource: WooResource) -> OrderSnapshot:
    identifier, customer_id = value.get("id"), value.get("customer_id")
    if type(identifier) is not int or identifier <= 0 or type(customer_id) is not int:
        raise OrderFailure("invalid_response")
    billing = record(value.get("billing"))
    items = value.get("line_items")
    if not isinstance(items, list):
        raise OrderFailure("invalid_response")
    meta = metadata(value)
    tracking: dict[str, str] = {}
    for target, key in (
        ("number", resource.tracking_number_meta),
        ("url", resource.tracking_url_meta),
    ):
        item = meta.get(key) if key else None
        if isinstance(item, str) and item:
            if target == "url" and (
                urlsplit(item).scheme != "https" or not urlsplit(item).hostname
            ):
                raise OrderFailure("invalid_tracking_url")
            tracking[target] = item
    return OrderSnapshot(
        order_id=str(identifier),
        customer_id=str(customer_id) if customer_id else None,
        email=email if isinstance(email := billing.get("email"), str) else None,
        status=resource.status_mapping.get(str(value.get("status")), "UNKNOWN"),
        version=digest(value),
        tracking=tracking or None,
        items=tuple(
            OrderItem.model_validate(
                {
                    "item_id": str(record(item).get("id", "")),
                    "name": record(item).get("name"),
                    "quantity": record(item).get("quantity"),
                    "sku": record(item).get("sku", ""),
                }
            )
            for item in items
        ),
        delivery={
            "shipping_address": strings(
                value.get("shipping"),
                (
                    "first_name",
                    "last_name",
                    "address_1",
                    "address_2",
                    "city",
                    "state",
                    "postcode",
                    "country",
                ),
            )
        },
    )


class WooCommerceConnector:
    manifest = WOOCOMMERCE_MANIFEST

    def __init__(
        self,
        *,
        binding: GoogleBinding,
        resource: WooResource,
        credential: ResolvedSecret,
        http: WooHTTP,
    ) -> None:
        self.binding, self.resource, self.http = binding, resource, http
        self.credential = decode(credential)

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        try:
            if (
                request.tenant_id != self.binding.tenant_id
                or request.binding_id != self.binding.binding_id
            ):
                raise OrderFailure("binding_mismatch")
            if self.resource.store_url != self.credential.store_url:
                raise OrderFailure("store_not_allowed")
            if (
                request.operation not in self.binding.operations
                or request.operation not in self.resource.supported_operations
            ):
                raise OrderFailure("operation_not_allowed")
            args = INPUTS[request.operation].model_validate(request.arguments)
            data = await self._execute(request, args)
            return ConnectorResult(
                operation=request.operation, status="SUCCEEDED", data=data
            )
        except ValidationError:
            return ConnectorResult(
                operation=request.operation,
                status="REJECTED",
                error_code="invalid_arguments",
            )
        except OrderFailure as error:
            return ConnectorResult(
                operation=request.operation,
                status="UNCERTAIN"
                if error.uncertain
                else "FAILED"
                if error.code
                in {"provider_unavailable", "rate_limited", "invalid_response"}
                else "REJECTED",
                error_code=error.code,
            )

    async def _get(self, order_id: str) -> dict[str, object]:
        if not re.fullmatch(r"[1-9][0-9]{0,18}", order_id):
            raise OrderFailure("order_not_found")
        value = record(
            await self.http.json(self.credential, "GET", "orders/" + order_id)
        )
        if str(value.get("id")) != order_id:
            raise OrderFailure("invalid_response")
        return value

    async def _execute(
        self, request: ConnectorRequest, args: InputModel
    ) -> dict[str, object]:
        if isinstance(args, FindOrder) and args.order_id is None:
            # WC only supports exact customer-ID filtering. Guest/email lookups
            # need the order ID; do not scan or disclose the entire store.
            if not args.customer.customer_id or not re.fullmatch(
                r"[1-9][0-9]*", args.customer.customer_id
            ):
                raise OrderFailure("order_id_required")
            payload = await self.http.json(
                self.credential,
                "GET",
                "orders",
                params={
                    "customer": args.customer.customer_id,
                    "page": str(args.page),
                    "per_page": str(args.limit),
                    "orderby": "id",
                    "order": "asc",
                },
            )
            if not isinstance(payload, list) or len(payload) > args.limit:
                raise OrderFailure("invalid_response")
            orders = [normalize(record(item), self.resource) for item in payload]
            return {
                "orders": [
                    order.read(READS[0])
                    for order in orders
                    if args.customer.matches(order.customer_id, order.email)
                ],
                "next_page": args.page + 1 if len(payload) == args.limit else None,
            }
        assert isinstance(args, (FindOrder, OrderRead)) and args.order_id is not None
        raw = await self._get(args.order_id)
        order = normalize(raw, self.resource)
        assert_owner(order, args.customer)
        if request.operation == READS[0]:
            return {"orders": [order.read(READS[0])], "next_page": None}
        if request.operation in READS:
            return order.read(request.operation)
        assert isinstance(args, OrderWrite)
        marker, parameter_digest = action_marker(request)
        if self.credential.permission != "read_write":
            raise OrderFailure("permission_denied")
        if isinstance(args, AddNote):
            return await self._note(request, args, order, marker, parameter_digest)
        key = "_agents_factory_action_" + marker
        receipt = metadata(raw).get(key)
        if receipt is not None:
            if receipt != parameter_digest:
                raise OrderFailure("idempotency_conflict")
            return write_result(order.order_id, request.operation, replayed=True)
        write_precondition(order, args.expected_version, request.operation)
        body: dict[str, object] = {
            "meta_data": [{"key": key, "value": parameter_digest}]
        }
        if isinstance(args, ShippingUpdate):
            body["shipping"] = args.address.model_dump()
        elif isinstance(args, ContactUpdate):
            body["billing"] = args.contact.model_dump(exclude_none=True)
        elif isinstance(args, CancelRequest):
            existing = metadata(raw).get("_agents_factory_cancellation_request")
            if existing:
                raise OrderFailure("cancellation_already_requested")
            body["meta_data"] = [
                {"key": key, "value": parameter_digest},
                {
                    "key": "_agents_factory_cancellation_request",
                    "value": json.dumps(
                        {
                            "action_id": marker,
                            "reason": args.reason,
                            "status": "REQUESTED",
                        }
                    ),
                },
            ]
        # Native WC has no atomic If-Match/CAS guarantee. The connection lease
        # serializes our workers; a concurrent external editor still needs review.
        result = await self.http.json(
            self.credential, "PUT", "orders/" + order.order_id, body=body
        )
        try:
            updated = record(result)
            if (
                str(updated.get("id")) != order.order_id
                or metadata(updated).get(key) != parameter_digest
            ):
                raise OrderFailure("invalid_response")
            for field in ("billing", "shipping"):
                if field in body and any(
                    record(updated.get(field)).get(k) != v
                    for k, v in record(body[field]).items()
                ):
                    raise OrderFailure("write_not_confirmed")
        except OrderFailure:
            raise OrderFailure("write_not_confirmed", uncertain=True) from None
        return write_result(order.order_id, request.operation)

    async def _note(
        self,
        request: ConnectorRequest,
        args: AddNote,
        order: OrderSnapshot,
        marker: str,
        parameter_digest: str,
    ) -> dict[str, object]:
        prefix = "AF-ACTION:" + marker + ":"
        note_marker = prefix + parameter_digest
        if "AF-ACTION:" in args.note:
            raise OrderFailure("invalid_arguments")
        # Bound pagination; refuse to append if an older marker could be hidden.
        for page in range(1, 11):
            notes = await self.http.json(
                self.credential,
                "GET",
                f"orders/{order.order_id}/notes",
                params={"page": str(page), "per_page": "100", "type": "internal"},
            )
            if not isinstance(notes, list) or len(notes) > 100:
                raise OrderFailure("invalid_response")
            for note in notes:
                body = record(note).get("note")
                if isinstance(body, str) and prefix in body:
                    if note_marker not in body:
                        raise OrderFailure("idempotency_conflict")
                    return write_result(
                        order.order_id, request.operation, replayed=True
                    )
            if len(notes) < 100:
                break
        else:
            raise OrderFailure("reconciliation_required")
        write_precondition(order, args.expected_version, request.operation)
        payload = await self.http.json(
            self.credential,
            "POST",
            f"orders/{order.order_id}/notes",
            body={
                "note": args.note + "\n[" + note_marker + "]",
                "customer_note": False,
            },
        )
        if (
            not isinstance(payload, dict)
            or not payload.get("id")
            or note_marker not in str(payload.get("note", ""))
        ):
            raise OrderFailure("write_not_confirmed", uncertain=True)
        return write_result(order.order_id, request.operation)


@dataclass(frozen=True)
class ConnectedWooCommerceConnector:
    service: IntegrationService
    context: TenantContext
    connection_id: UUID
    binding: GoogleBinding
    resource: WooResource
    http: WooHTTP

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        return await self.service.execute_connector(
            context=self.context,
            connection_id=self.connection_id,
            connector_name="woocommerce",
            request=request,
            build=lambda credential: WooCommerceConnector(
                binding=self.binding,
                resource=self.resource,
                credential=credential,
                http=self.http,
            ),
        )
