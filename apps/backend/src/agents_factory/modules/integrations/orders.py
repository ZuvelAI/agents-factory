"""Provider-neutral order contracts; identity/action authorization belongs to Task 26."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, model_validator

from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.google.base import InputModel
from agents_factory.modules.agent_factory.models import ConnectorBinding


READS = (
    "orders.find_order",
    "orders.get_status",
    "orders.get_tracking",
    "orders.get_items",
    "orders.get_delivery_information",
)
WRITES = (
    "orders.update_shipping_address",
    "orders.update_contact_information",
    "orders.add_order_note",
    "orders.request_order_cancellation",
)
OPERATIONS = READS + WRITES


class OrderResource(Protocol):
    @property
    def supported_operations(self) -> tuple[str, ...]: ...


def configured_order_binding(
    *,
    binding_id: UUID,
    connector: Literal["woocommerce", "google_sheets"],
    resource: OrderResource,
    allow_writes: bool = False,
) -> ConnectorBinding:
    """Trusted setup derives AgentSpec operations from tested mapping/permissions.

    `allow_writes` must reflect admin-approved provider grants, never model input.
    The adapters independently enforce this same mapping at execution time.
    """
    return ConnectorBinding(
        binding_id=binding_id,
        connector=connector,
        connector_version="1.0.0",
        operations=tuple(
            op for op in resource.supported_operations if allow_writes or op in READS
        ),
    )


Text = Annotated[str, Field(min_length=1, max_length=300)]
Status = Literal[
    "PENDING",
    "PROCESSING",
    "ON_HOLD",
    "COMPLETED",
    "CANCELLED",
    "REFUNDED",
    "FAILED",
    "SHIPPED",
    "UNKNOWN",
]
STATUS_MAP: dict[str, Status] = {
    "pending": "PENDING",
    "processing": "PROCESSING",
    "on-hold": "ON_HOLD",
    "completed": "COMPLETED",
    "cancelled": "CANCELLED",
    "refunded": "REFUNDED",
    "failed": "FAILED",
    "shipped": "SHIPPED",
}


class OrderFailure(Exception):
    def __init__(self, code: str, *, uncertain: bool = False) -> None:
        self.code, self.uncertain = code, uncertain
        super().__init__(code)


class CustomerMatch(InputModel):
    # Supplied by trusted backend identity resolution, NOT proof of identity itself.
    customer_id: Text | None = None
    verified_email: str | None = Field(
        default=None, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    )

    @model_validator(mode="after")
    def identified(self) -> Self:
        if not self.customer_id and not self.verified_email:
            raise ValueError("customer match required")
        if self.customer_id == "0":
            raise ValueError("guest ID is not a customer identity")
        return self

    def matches(self, customer_id: str | None, email: str | None) -> bool:
        return (self.customer_id is None or self.customer_id == customer_id) and (
            self.verified_email is None
            or self.verified_email.casefold() == (email or "").casefold()
        )


class FindOrder(InputModel):
    customer: CustomerMatch
    order_id: Text | None = None
    page: int = Field(default=1, ge=1, le=1000)
    limit: int = Field(default=25, ge=1, le=50)


class OrderRead(InputModel):
    customer: CustomerMatch
    order_id: Text


class Address(InputModel):
    first_name: Text
    last_name: Text
    address_1: Text
    address_2: str = Field(default="", max_length=300)
    city: Text
    state: str = Field(default="", max_length=100)
    postcode: Text
    country: str = Field(pattern=r"^[A-Z]{2}$")


class Contact(InputModel):
    email: str | None = Field(
        default=None, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    )
    phone: str | None = Field(
        default=None, min_length=5, max_length=30, pattern=r"^[+0-9 ()-]+$"
    )

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if self.email is None and self.phone is None:
            raise ValueError("contact update empty")
        return self


class OrderWrite(OrderRead):
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")


class ShippingUpdate(OrderWrite):
    address: Address


class ContactUpdate(OrderWrite):
    contact: Contact


class AddNote(OrderWrite):
    note: str = Field(min_length=1, max_length=2000)


class CancelRequest(OrderWrite):
    reason: str = Field(min_length=1, max_length=2000)


INPUTS: dict[str, type[InputModel]] = {
    READS[0]: FindOrder,
    **{operation: OrderRead for operation in READS[1:]},
    WRITES[0]: ShippingUpdate,
    WRITES[1]: ContactUpdate,
    WRITES[2]: AddNote,
    WRITES[3]: CancelRequest,
}


class OrderItem(InputModel):
    item_id: str
    name: str = Field(max_length=500)
    quantity: int = Field(ge=0)
    sku: str = Field(default="", max_length=200)


class OrderSnapshot(InputModel):
    order_id: str
    customer_id: str | None = None
    email: str | None = None
    status: Status
    version: str
    tracking: dict[str, str] | None = None
    items: tuple[OrderItem, ...] = ()
    delivery: dict[str, object] = Field(default_factory=dict)

    def read(self, operation: str) -> dict[str, object]:
        result: dict[str, object] = {"order_id": self.order_id, "version": self.version}
        if operation in {READS[0], READS[1]}:
            result["status"] = self.status
        elif operation == READS[2]:
            result.update(
                {"tracking": self.tracking, "tracking_available": bool(self.tracking)}
            )
        elif operation == READS[3]:
            result["items"] = [item.model_dump() for item in self.items]
        elif operation == READS[4]:
            result["delivery"] = self.delivery
        return result


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def action_marker(request: ConnectorRequest) -> tuple[str, str]:
    if request.idempotency_key is None:
        raise OrderFailure("idempotency_key_required")
    key = hashlib.sha256(
        f"{request.tenant_id}:{request.binding_id}:{request.idempotency_key}".encode()
    ).hexdigest()
    return key, digest({"operation": request.operation, "arguments": request.arguments})


def assert_owner(order: OrderSnapshot, customer: CustomerMatch) -> None:
    if not customer.matches(order.customer_id, order.email):
        raise OrderFailure("order_not_found")


def write_precondition(order: OrderSnapshot, expected: str, operation: str) -> None:
    if order.version != expected:
        raise OrderFailure("stale_version")
    if operation != "orders.add_order_note" and (
        order.status not in {"PENDING", "PROCESSING", "ON_HOLD"} or order.tracking
    ):
        raise OrderFailure("order_not_mutable")


def write_result(
    order_id: str, operation: str, *, replayed: bool = False
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "operation": operation,
        "replayed": replayed,
        **(
            {"cancellation_requested": True, "cancellation_executed": False}
            if operation == WRITES[3]
            else {"applied": True}
        ),
    }
