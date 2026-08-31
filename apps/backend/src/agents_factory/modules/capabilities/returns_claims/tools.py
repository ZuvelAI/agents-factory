from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid5

from agents_factory.modules.actions.models import NormalizedParameters
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.capabilities.returns_claims.manifest import (
    RETURNS_CLAIMS_MANIFEST,
)
from agents_factory.modules.capabilities.returns_claims.workflow import (
    ClaimNeedsInformation,
    ClaimsWorkflow,
    STATUS,
)
from agents_factory.modules.runtime.contracts import RuntimeTool, ToolInvocationContext


@dataclass(frozen=True)
class ClaimsToolSession:
    context: ToolInvocationContext
    workflow: ClaimsWorkflow
    actions: ActionService
    binding_id: UUID
    customer_ref: str
    language: str = "es"

    def tools(self) -> tuple[RuntimeTool, ...]:
        try:
            configuration = self.workflow.configuration(self.binding_id)
        except ValueError:
            return ()
        tools = []
        for definition in RETURNS_CLAIMS_MANIFEST.actions:
            if not self.workflow.supports(configuration, definition.name):
                continue

            async def handle(
                context: ToolInvocationContext,
                arguments: Mapping[str, object],
                *,
                operation: str = definition.name,
            ) -> object:
                if (
                    context != self.context
                    or context.tenant_id != self.workflow.context.tenant_id
                ):
                    return {
                        "state": "REJECTED",
                        "reason_code": "claim_context_mismatch",
                    }
                try:
                    digest = NormalizedParameters.from_value(dict(arguments)).digest
                    action = await self.workflow.request_action(
                        actions=self.actions,
                        action_id=uuid5(
                            context.inbound_message_id,
                            f"{self.binding_id}:{operation}:{digest}",
                        ),
                        message_id=context.inbound_message_id,
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
                    ) or action.state in {
                        "SUCCEEDED",
                        "FAILED",
                        "UNCERTAIN",
                        "REJECTED",
                        "EXPIRED",
                        "HANDED_OFF",
                    }:
                        result = await self.actions.execute(action_id=action.id)
                        return {
                            **result.model_dump(mode="json"),
                            "customer_message": customer_message(
                                state=result.state,
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
                except ClaimNeedsInformation as error:
                    return {
                        "state": "NEEDS_INFORMATION",
                        "missing_fields": error.fields,
                        "case_created": False,
                    }
                except Exception:
                    return {
                        "state": "UNAVAILABLE",
                        "reason_code": "claim_request_unavailable",
                        "customer_message": customer_message(
                            state="FAILED", operation=operation, language=self.language
                        ),
                    }

            tools.append(
                RuntimeTool(
                    name=definition.name,
                    capability="returns_claims",
                    description=definition.description,
                    input_schema=definition.input_schema,
                    handler=handle,
                )
            )
        return tuple(tools)


def customer_message(*, state: str, operation: str, language: str) -> str:
    if state == "SUCCEEDED":
        if operation == STATUS:
            return (
                "Consulta de estado completada."
                if language == "es"
                else "Case status lookup completed."
            )
        return (
            "El caso quedó registrado para revisión; no implica aceptación ni reembolso. Revisa también el estado de entrega al backoffice."
            if language == "es"
            else "The case was recorded for review; acceptance or a refund has not been promised. Check the separate backoffice delivery status."
        )
    return (
        "No pude confirmar la operación. Se necesita revisión; no se repetirá automáticamente."
        if language == "es"
        else "I could not confirm the operation. Review is required; it will not be repeated automatically."
    )
