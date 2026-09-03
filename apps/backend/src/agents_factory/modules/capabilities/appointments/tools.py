from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import uuid5

from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.capabilities.appointments.manifest import (
    APPOINTMENTS_MANIFEST,
)
from agents_factory.modules.capabilities.appointments.models import AppointmentsConfig
from agents_factory.modules.capabilities.appointments.service import AppointmentsService
from agents_factory.modules.identity.models import IdentityAssessment
from agents_factory.modules.integrations.contracts import Connector
from agents_factory.modules.integrations.google.base import GoogleBinding, GoogleHTTP
from agents_factory.modules.integrations.google.calendar import (
    CalendarResource,
    GoogleCalendarConnector,
)
from agents_factory.modules.integrations.google.factory import ConnectedGoogleConnector
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.common.context import TenantContext
from agents_factory.modules.runtime.contracts import RuntimeTool, ToolInvocationContext


@dataclass(frozen=True)
class GoogleAppointmentCalendarFactory:
    integrations: IntegrationService
    context: TenantContext
    http: GoogleHTTP

    def __call__(self, config: AppointmentsConfig) -> Connector:
        return ConnectedGoogleConnector(
            service=self.integrations,
            context=self.context,
            connection_id=config.connection_id,
            product="google_calendar",
            binding=GoogleBinding(
                self.context.tenant_id,
                config.binding_id,
                frozenset(GoogleCalendarConnector.manifest.supported_operations),
            ),
            resource=CalendarResource(calendar_id=config.calendar_id),
            http=self.http,
        )


@dataclass(frozen=True)
class AppointmentToolSession:
    """Per-turn backend composition; assessment/customer never come from the model.

    Request transaction must commit before confirmation or execution of a write.
    Only the existing trusted ActionService confirmation/approval paths advance it.
    """

    context: ToolInvocationContext
    appointments: AppointmentsService
    actions: ActionService
    customer_ref: str
    assessment: IdentityAssessment

    def tools(self) -> tuple[RuntimeTool, ...]:
        tools: list[RuntimeTool] = []
        for definition in APPOINTMENTS_MANIFEST.actions:
            operation = definition.name

            async def handler(
                context: ToolInvocationContext,
                arguments: Mapping[str, object],
                *,
                name: str = operation,
            ) -> object:
                if (
                    context != self.context
                    or context.tenant_id != self.appointments.context.tenant_id
                ):
                    return {
                        "status": "REJECTED",
                        "reason_code": "appointment_context_mismatch",
                    }
                digest = NormalizedParameters.from_value(dict(arguments)).digest
                action_id = uuid5(context.inbound_message_id, f"{name}:{digest}")
                action = await self.appointments.request_action(
                    actions=self.actions,
                    action_id=action_id,
                    conversation_id=context.conversation_id,
                    customer_ref=self.customer_ref,
                    operation=name,
                    arguments=dict(arguments),
                    assessment=self.assessment,
                )
                if action.state == "CONFIRMED" and not action.approval_required:
                    return (await self.actions.execute(action_id=action.id)).model_dump(
                        mode="json"
                    )
                return {
                    "action_id": str(action.id),
                    "state": action.state,
                    "parameter_digest": action.parameter_digest,
                    "parameters": action.parameters,
                }

            tools.append(
                RuntimeTool(
                    name=operation,
                    capability="appointments",
                    description=definition.description,
                    input_schema=definition.input_schema,
                    handler=handler,
                )
            )
        return tuple(tools)
