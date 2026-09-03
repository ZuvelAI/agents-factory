from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid5

from pydantic import ValidationError

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.capabilities.orders.issues import IssueNeedsInformation
from agents_factory.modules.capabilities.orders.manifest import ORDERS_MANIFEST
from agents_factory.modules.capabilities.orders.models import OrdersBinding
from agents_factory.modules.capabilities.orders.service import (
    OrderCustomer,
    OrderUnavailable,
    OrdersService,
    customer_message,
)
from agents_factory.modules.identity.service import IdentityService
from agents_factory.modules.integrations.contracts import Connector
from agents_factory.modules.integrations.google.base import GoogleBinding, GoogleHTTP
from agents_factory.modules.integrations.google.factory import ConnectedGoogleConnector
from agents_factory.modules.integrations.google.orders_sheet import OrdersSheetResource
from agents_factory.modules.integrations.orders import CustomerMatch
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.integrations.woocommerce.auth import WooHTTP
from agents_factory.modules.integrations.woocommerce.client import (
    ConnectedWooCommerceConnector,
    WooResource,
)
from agents_factory.modules.runtime.contracts import RuntimeTool, ToolInvocationContext


class OrderCustomerDirectory(Protocol):
    async def match(
        self, *, context: TenantContext, customer_ref: str, binding_id: UUID
    ) -> CustomerMatch | None:
        """Read trusted tenant-owned customer links; never accept a model's claim."""
        ...


@dataclass(frozen=True)
class VerifiedOrderCustomers:
    identities: IdentityService
    directory: OrderCustomerDirectory

    async def resolve(
        self,
        *,
        context: TenantContext,
        customer_ref: str,
        binding_id: UUID,
        action_id: UUID,
    ) -> OrderCustomer | None:
        assessment = await self.identities.assess(
            customer_ref, action_ref=str(action_id)
        )
        if assessment.tenant_id != context.tenant_id:
            return None
        match = await self.directory.match(
            context=context, customer_ref=customer_ref, binding_id=binding_id
        )
        return OrderCustomer(assessment, match) if match is not None else None


@dataclass(frozen=True)
class NativeOrderConnectors:
    integrations: IntegrationService
    context: TenantContext
    google_http: GoogleHTTP
    woo_http: WooHTTP

    def __call__(self, configuration: OrdersBinding) -> Connector:
        if configuration.tenant_id != self.context.tenant_id:
            raise OrderUnavailable("order_binding_unavailable")
        binding = GoogleBinding(
            configuration.tenant_id,
            configuration.binding_id,
            frozenset(configuration.operations),
        )
        if configuration.connector == "woocommerce" and isinstance(
            configuration.resource, WooResource
        ):
            return ConnectedWooCommerceConnector(
                service=self.integrations,
                context=self.context,
                connection_id=configuration.connection_id,
                binding=binding,
                resource=configuration.resource,
                http=self.woo_http,
            )
        if isinstance(configuration.resource, OrdersSheetResource):
            return ConnectedGoogleConnector(
                service=self.integrations,
                context=self.context,
                connection_id=configuration.connection_id,
                product="google_sheets",
                binding=binding,
                resource=configuration.resource,
                http=self.google_http,
            )
        raise OrderUnavailable("order_binding_unavailable")


@dataclass(frozen=True)
class OrdersToolSession:
    context: ToolInvocationContext
    orders: OrdersService
    actions: ActionService
    binding_id: UUID
    customer_ref: str
    language: str = "es"

    def tools(self) -> tuple[RuntimeTool, ...]:
        try:
            binding = self.orders.binding(self.binding_id)
        except OrderUnavailable:
            return ()
        result = []
        for definition in ORDERS_MANIFEST.actions:
            if not self.orders.supports(binding, definition.name):
                continue

            async def handle(
                context: ToolInvocationContext,
                arguments: Mapping[str, object],
                *,
                operation: str = definition.name,
            ) -> object:
                if (
                    context != self.context
                    or context.tenant_id != self.orders.context.tenant_id
                ):
                    return {
                        "state": "REJECTED",
                        "reason_code": "order_context_mismatch",
                    }
                try:
                    digest = NormalizedParameters.from_value(dict(arguments)).digest
                    action_id = uuid5(
                        context.inbound_message_id,
                        f"{self.binding_id}:{operation}:{digest}",
                    )
                    action = await self.orders.request_action(
                        actions=self.actions,
                        action_id=action_id,
                        conversation_id=context.conversation_id,
                        customer_ref=self.customer_ref,
                        binding_id=self.binding_id,
                        operation=operation,
                        arguments=dict(arguments),
                    )
                    if (
                        action.state == "CONFIRMED"
                        and not action.confirmation_required
                        and not action.approval_required
                        or action.state
                        in {
                            "SUCCEEDED",
                            "FAILED",
                            "UNCERTAIN",
                            "REJECTED",
                            "EXPIRED",
                            "HANDED_OFF",
                        }
                    ):
                        outcome = await self.actions.execute(action_id=action.id)
                        return {
                            **outcome.model_dump(mode="json"),
                            "customer_message": customer_message(
                                state=outcome.state,
                                operation=operation,
                                language=self.language,
                            ),
                        }
                    return {
                        "action_id": str(action.id),
                        "state": action.state,
                        "parameter_digest": action.parameter_digest,
                        "parameters": {
                            key: value
                            for key, value in action.parameters.items()
                            if not key.startswith("_")
                        },
                    }
                except IssueNeedsInformation as error:
                    return {
                        "state": "NEEDS_INFORMATION",
                        "missing_fields": error.fields,
                        "case_created": False,
                    }
                except (OrderUnavailable, DomainError, ValidationError) as error:
                    reason = (
                        str(error)
                        if isinstance(error, OrderUnavailable)
                        else "order_request_rejected"
                    )
                    return {
                        "state": "UNAVAILABLE",
                        "reason_code": reason,
                        "customer_message": customer_message(
                            state="FAILED", operation=operation, language=self.language
                        ),
                    }

            result.append(
                RuntimeTool(
                    name=definition.name,
                    capability="orders",
                    description=definition.description,
                    input_schema=definition.input_schema,
                    handler=handle,
                )
            )
        return tuple(result)
