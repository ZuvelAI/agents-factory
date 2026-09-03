from __future__ import annotations

import json
from dataclasses import replace
from typing import Self

from pydantic import Field, ValidationError, model_validator

from agents_factory.modules.integrations.contracts import (
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.integrations.google.base import GoogleBinding, GoogleHTTP
from agents_factory.modules.integrations.google.sheets import (
    Cell,
    GoogleSheetsConnector,
    SheetsResource,
)
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
from agents_factory.modules.secrets.redaction import ResolvedSecret


WRITE_FIELDS = dict(
    zip(
        WRITES,
        ("shipping_address", "contact_information", "notes", "cancellation_request"),
    )
)
FIELDS = frozenset(
    {
        "order_id",
        "customer_id",
        "email",
        "status",
        "tracking",
        "items",
        "shipping_address",
        "delivery_information",
        "contact_information",
        "notes",
        "cancellation_request",
        "action_receipts",
    }
)


class OrdersSheetResource(SheetsResource):
    writable_fields: frozenset[str] = frozenset()
    status_mapping: dict[str, Status] = Field(default_factory=lambda: dict(STATUS_MAP))

    @model_validator(mode="after")
    def order_mapping(self) -> Self:
        if (
            not {"order_id", "status"}.issubset(self.fields)
            or not {"customer_id", "email"}.intersection(self.fields)
            or not set(self.fields).issubset(FIELDS)
            or not self.writable_fields.issubset(self.fields)
            or not self.writable_fields.issubset(
                {*WRITE_FIELDS.values(), "action_receipts"}
            )
        ):
            raise ValueError("invalid order field mapping")
        return self

    @property
    def supported_operations(self) -> tuple[str, ...]:
        operations = [READS[0], READS[1]]
        for operation, fields in (
            (READS[2], {"tracking"}),
            (READS[3], {"items"}),
            (READS[4], {"shipping_address", "delivery_information"}),
        ):
            if fields.intersection(self.fields):
                operations.append(operation)
        if "action_receipts" in self.writable_fields:
            operations.extend(
                op
                for op, field in WRITE_FIELDS.items()
                if field in self.writable_fields
            )
        return tuple(operations)


def structured(value: Cell | None, default: object) -> object:
    if value in (None, ""):
        return default
    if not isinstance(value, str):
        raise OrderFailure("invalid_order_mapping")
    try:
        return json.loads(value)
    except ValueError:
        raise OrderFailure("invalid_order_mapping") from None


def object_cell(row: dict[str, Cell], key: str) -> dict[str, object]:
    value = structured(row.get(key), {})
    if not isinstance(value, dict):
        raise OrderFailure("invalid_order_mapping")
    return value


def normalized(row: dict[str, Cell], resource: OrdersSheetResource) -> OrderSnapshot:
    order_id = str(row.get("order_id", ""))
    if not order_id:
        raise OrderFailure("invalid_order_mapping")
    contact = object_cell(row, "contact_information")
    email = contact.get("email", row.get("email"))
    tracking = object_cell(row, "tracking") or None
    if tracking and (
        set(tracking) - {"number", "url"}
        or any(not isinstance(value, str) for value in tracking.values())
    ):
        raise OrderFailure("invalid_order_mapping")
    if tracking and "url" in tracking:
        from urllib.parse import urlsplit

        url = urlsplit(str(tracking["url"]))
        if url.scheme != "https" or not url.hostname:
            raise OrderFailure("invalid_tracking_url")
    return OrderSnapshot.model_validate(
        {
            "order_id": order_id,
            "customer_id": str(row["customer_id"])
            if row.get("customer_id") not in (None, "", "0", 0)
            else None,
            "email": email if isinstance(email, str) and email else None,
            "status": resource.status_mapping.get(str(row.get("status")), "UNKNOWN"),
            "version": digest(row),
            "tracking": tracking,
            "items": structured(row.get("items"), []),
            "delivery": {
                **object_cell(row, "delivery_information"),
                **(
                    {"shipping_address": object_cell(row, "shipping_address")}
                    if "shipping_address" in row
                    else {}
                ),
            },
        }
    )


class OrdersSheetConnector:
    """Native Sheets domain mapping inside the same backend credential lease."""

    def __init__(
        self,
        *,
        binding: GoogleBinding,
        resource: OrdersSheetResource,
        credential: ResolvedSecret,
        http: GoogleHTTP,
    ) -> None:
        self.binding, self.resource = binding, resource
        native_ops = {"sheets.read_rows"}
        if set(binding.operations).intersection(WRITES):
            native_ops.add("sheets.update_row")
        self.native = GoogleSheetsConnector(
            binding=replace(binding, operations=frozenset(native_ops)),
            resource=resource,
            credential=credential,
            http=http,
        )

    async def _call(
        self, request: ConnectorRequest, operation: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        result = await self.native.execute(
            request.model_copy(update={"operation": operation, "arguments": arguments})
        )
        if result.status != "SUCCEEDED":
            raise OrderFailure(
                result.error_code or "provider_unavailable",
                uncertain=result.status == "UNCERTAIN",
            )
        return result.data

    async def _rows(
        self, request: ConnectorRequest, start: int, limit: int
    ) -> tuple[list[tuple[int, dict[str, Cell]]], int | None]:
        data = await self._call(
            request, "sheets.read_rows", {"start_row": start, "limit": limit}
        )
        # Task 23 already validates the provider cell shape; enforce domain envelope.
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise OrderFailure("invalid_response")
        result: list[tuple[int, dict[str, Cell]]] = []
        for entry in rows:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("row_number"), int)
                or not isinstance(entry.get("values"), dict)
            ):
                raise OrderFailure("invalid_response")
            result.append((entry["row_number"], entry["values"]))
        # A short/empty fixed-range response does not exclude rows after a gap.
        next_row = start + limit
        return result, next_row if next_row <= self.resource.max_rows else None

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        try:
            if (
                request.tenant_id != self.binding.tenant_id
                or request.binding_id != self.binding.binding_id
            ):
                raise OrderFailure("binding_mismatch")
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

    async def _execute(
        self, request: ConnectorRequest, args: object
    ) -> dict[str, object]:
        assert isinstance(args, (FindOrder, OrderRead))
        if isinstance(args, FindOrder) and args.order_id is None:
            rows, next_row = await self._rows(
                request, 2 + (args.page - 1) * args.limit, args.limit
            )
            orders = [
                normalized(row, self.resource) for _, row in rows if row.get("order_id")
            ]
            return {
                "orders": [
                    order.read(READS[0])
                    for order in orders
                    if args.customer.matches(order.customer_id, order.email)
                ],
                "next_page": args.page + 1 if next_row is not None else None,
            }
        matches: list[tuple[int, dict[str, Cell]]] = []
        start: int | None = 2
        while start is not None:
            rows, start = await self._rows(request, start, 500)
            matches.extend(
                (number, row)
                for number, row in rows
                if str(row.get("order_id")) == args.order_id
            )
            if len(matches) > 1:
                raise OrderFailure("ambiguous_order_mapping")
        if not matches:
            raise OrderFailure("order_not_found")
        row_number, row = matches[0]
        order = normalized(row, self.resource)
        assert_owner(order, args.customer)
        if request.operation == READS[0]:
            return {"orders": [order.read(READS[0])], "next_page": None}
        if request.operation in READS:
            return order.read(request.operation)
        assert isinstance(args, OrderWrite)
        marker, parameter_digest = action_marker(request)
        receipts = object_cell(row, "action_receipts")
        if marker in receipts:
            if receipts[marker] != parameter_digest:
                raise OrderFailure("idempotency_conflict")
            return write_result(order.order_id, request.operation, replayed=True)
        write_precondition(order, args.expected_version, request.operation)
        changes: dict[str, Cell] = {}
        if isinstance(args, ShippingUpdate):
            changes["shipping_address"] = json.dumps(args.address.model_dump())
        elif isinstance(args, ContactUpdate):
            changes["contact_information"] = json.dumps(
                {
                    **object_cell(row, "contact_information"),
                    **args.contact.model_dump(exclude_none=True),
                }
            )
        elif isinstance(args, AddNote):
            notes = structured(row.get("notes"), [])
            if not isinstance(notes, list):
                raise OrderFailure("invalid_order_mapping")
            changes["notes"] = json.dumps(
                [*notes, {"action_id": marker, "note": args.note}]
            )
        elif isinstance(args, CancelRequest):
            if object_cell(row, "cancellation_request"):
                raise OrderFailure("cancellation_already_requested")
            changes["cancellation_request"] = json.dumps(
                {"action_id": marker, "reason": args.reason, "status": "REQUESTED"}
            )
        changes["action_receipts"] = json.dumps({**receipts, marker: parameter_digest})
        if any(len(str(value)) > 45000 for value in changes.values()):
            raise OrderFailure("reconciliation_required")
        # Native adapter re-reads headers and this exact row before writing only
        # changed cells, including the action receipt, in one RAW batchUpdate.
        await self._call(
            request,
            "sheets.update_row",
            {"row_number": row_number, "expected": row, "values": changes},
        )
        return write_result(order.order_id, request.operation)
