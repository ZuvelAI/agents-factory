from __future__ import annotations

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.cases.contracts import IssueType
from agents_factory.modules.integrations.google.base import InputModel
from agents_factory.modules.integrations.google.orders_sheet import OrdersSheetResource
from agents_factory.modules.integrations.orders import (
    Address,
    Contact,
    READS,
    WRITES,
    configured_order_binding,
)
from agents_factory.modules.integrations.woocommerce.client import WooResource


class OrdersBinding(InputModel):
    tenant_id: UUID
    binding_id: UUID
    connection_id: UUID
    connector: Literal["woocommerce", "google_sheets"]
    resource: WooResource | OrdersSheetResource
    allow_writes: bool = False
    enabled: bool = True
    approval_route_ref: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def matching_resource(self) -> Self:
        if (self.connector == "woocommerce") != isinstance(self.resource, WooResource):
            raise ValueError("order provider/resource mismatch")
        if WRITES[3] in self.operations and not self.approval_route_ref:
            raise ValueError("cancellation approval route required")
        return self

    @property
    def operations(self) -> tuple[str, ...]:
        if not self.enabled:
            return ()
        return configured_order_binding(
            binding_id=self.binding_id,
            connector=self.connector,
            resource=self.resource,
            allow_writes=self.allow_writes,
        ).operations

    @property
    def digest(self) -> str:
        value = self.model_dump(mode="json")
        for field in ("writable_fields", "writable_operations"):
            if field in value["resource"]:
                value["resource"][field] = sorted(value["resource"][field])
        return NormalizedParameters.from_value(value).digest


class FindOrder(InputModel):
    order_id: str | None = Field(default=None, min_length=1, max_length=300)
    page: int = Field(default=1, ge=1, le=1000)
    limit: int = Field(default=25, ge=1, le=50)


class OrderRead(InputModel):
    order_id: str = Field(min_length=1, max_length=300)


class ShippingUpdate(OrderRead):
    address: Address


class ContactUpdate(OrderRead):
    contact: Contact


class AddNote(OrderRead):
    note: str = Field(min_length=1, max_length=2000)


class CancelRequest(OrderRead):
    reason: str = Field(min_length=1, max_length=2000)


class IssueDraft(InputModel):
    issue_type: IssueType
    order_id: str | None = Field(default=None, min_length=1, max_length=300)
    purchase_reference: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    item_ids: tuple[str, ...] = Field(default=(), max_length=50)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=20)
    incident_date: date | None = None
    requested_resolution: str | None = Field(
        default=None, min_length=1, max_length=1000
    )


INPUTS: dict[str, type[InputModel]] = {
    READS[0]: FindOrder,
    **{op: OrderRead for op in READS[1:]},
    WRITES[0]: ShippingUpdate,
    WRITES[1]: ContactUpdate,
    WRITES[2]: AddNote,
    WRITES[3]: CancelRequest,
    "orders.create_claim": IssueDraft,
}
