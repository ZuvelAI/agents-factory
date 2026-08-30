from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.modules.actions.models import (
    ActionRecord,
    NormalizedParameters,
    PreconditionDecision,
)
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.cases.contracts import (
    CasesPort,
    UnavailableCases,
    CasesUnavailable,
)
from agents_factory.modules.capabilities.orders.issues import (
    DenyEvidence,
    EvidenceAccess,
    IssueNeedsInformation,
    case_intake,
    missing_information,
)
from agents_factory.modules.capabilities.orders.manifest import DEFINITIONS, action_gate
from agents_factory.modules.capabilities.orders.models import (
    INPUTS,
    IssueDraft,
    OrdersBinding,
)
from agents_factory.modules.capabilities.orders.repository import OrderReceipts
from agents_factory.modules.identity.models import (
    AuthorizationDecision,
    IdentityAssessment,
    IdentityLevel,
)
from agents_factory.modules.integrations.contracts import (
    Connector,
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.integrations.orders import CustomerMatch, READS, WRITES
from agents_factory.modules.policies.evaluator import ActionPolicyEvaluator
from agents_factory.modules.policies.models import TenantActionPolicy
from agents_factory.modules.runtime.contracts import reject_sensitive_fields


class OrderUnavailable(ValueError):
    """A code-owned safe reason. Provider diagnostics never enter this exception."""


@dataclass(frozen=True)
class OrderCustomer:
    assessment: IdentityAssessment
    match: CustomerMatch


class OrderCustomerResolver(Protocol):
    async def resolve(
        self,
        *,
        context: TenantContext,
        customer_ref: str,
        binding_id: UUID,
        action_id: UUID,
    ) -> OrderCustomer | None: ...


class OrderConnectorFactory(Protocol):
    def __call__(self, binding: OrdersBinding) -> Connector: ...


class OrdersService:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        context: TenantContext,
        bindings: Callable[[UUID], OrdersBinding | None],
        customers: OrderCustomerResolver,
        connectors: OrderConnectorFactory,
        cases: CasesPort | None = None,
        evidence: EvidenceAccess | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions, self.context, self.bindings = sessions, context, bindings
        self.customers, self.connectors = customers, connectors
        self.cases, self.evidence = (
            cases or UnavailableCases(),
            evidence or DenyEvidence(),
        )
        self.now = now or (lambda: datetime.now(UTC))

    def binding(self, binding_id: UUID) -> OrdersBinding:
        if (
            self.context.actor_type not in {"system", "platform_admin"}
            or self.context.actor_id is None
        ):
            raise OrderUnavailable("backend_actor_required")
        binding = self.bindings(binding_id)
        if (
            binding is None
            or binding.tenant_id != self.context.tenant_id
            or not binding.enabled
        ):
            raise OrderUnavailable("order_binding_unavailable")
        return binding

    def supports(self, binding: OrdersBinding, operation: str) -> bool:
        definition = DEFINITIONS.get(operation)
        return bool(
            definition
            and set(definition.required_connector_operations).issubset(
                binding.operations
            )
            and (operation != "orders.create_claim" or self.cases.available)
        )

    async def customer(
        self, customer_ref: str, binding_id: UUID, action_id: UUID, level: int
    ) -> OrderCustomer:
        value = await self.customers.resolve(
            context=self.context,
            customer_ref=customer_ref,
            binding_id=binding_id,
            action_id=action_id,
        )
        if (
            value is None
            or value.assessment.tenant_id != self.context.tenant_id
            or value.assessment.customer_ref != customer_ref
            or value.assessment.achieved_level < level
        ):
            raise OrderUnavailable("order_identity_required")
        age = self.now() - value.assessment.assessed_at
        if age < timedelta(seconds=-30) or age > timedelta(minutes=5):
            raise OrderUnavailable("order_identity_required")
        return value

    async def request_action(
        self,
        *,
        actions: ActionService,
        action_id: UUID,
        conversation_id: UUID,
        customer_ref: str,
        binding_id: UUID,
        operation: str,
        arguments: dict[str, object],
        tenant_policy: TenantActionPolicy | None = None,
    ) -> ActionRecord:
        binding = self.binding(binding_id)
        if operation not in DEFINITIONS:
            raise OrderUnavailable("order_operation_unavailable")
        params = INPUTS[operation].model_validate(arguments).model_dump(mode="json")
        if operation == "orders.create_claim":
            missing = missing_information(IssueDraft.model_validate(params))
            if missing:
                raise IssueNeedsInformation(missing)
        if not self.supports(binding, operation):
            raise OrderUnavailable(
                "case_creation_unavailable"
                if operation == "orders.create_claim"
                else "order_operation_unavailable"
            )
        definition = DEFINITIONS[operation]
        requirement = ActionPolicyEvaluator().evaluate(
            risk=definition.risk,
            minimum_identity_level=IdentityLevel(definition.required_identity_level),
            tenant_policy=tenant_policy,
        )
        customer = await self.customer(
            customer_ref, binding_id, action_id, int(requirement.identity_level)
        )
        request_digest = NormalizedParameters.from_value(params).digest
        # Stable inbound replays must reuse the original snapshot/confirmation.
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            existing = await ActionRepository(session, self.context).get(action_id)
        if existing is not None:
            if (
                existing.customer_ref,
                existing.conversation_id,
                existing.connector_binding_id,
                existing.action_type,
                existing.parameters.get("_request_digest"),
            ) != (customer_ref, conversation_id, binding_id, operation, request_digest):
                raise OrderUnavailable("order_idempotency_conflict")
            return existing
        verified = False
        if isinstance(params.get("order_id"), str):
            result = await self._provider(
                binding,
                READS[1],
                {
                    "order_id": params["order_id"],
                    "customer": customer.match.model_dump(exclude_none=True),
                },
            )
            if result.status != "SUCCEEDED":
                is_missing = (
                    operation == "orders.create_claim"
                    and params.get("issue_type") == "missing_order"
                )
                if not is_missing:
                    raise OrderUnavailable(safe_reason(result))
            else:
                verified = True
                if operation in WRITES:
                    version = result.data.get("version")
                    if not isinstance(version, str):
                        raise OrderUnavailable("order_read_unavailable")
                    params["expected_version"] = version
        if operation == "orders.create_claim":
            await self._check_evidence(customer_ref, IssueDraft.model_validate(params))
        params.update(
            {
                "_request_digest": request_digest,
                "_configuration_digest": binding.digest,
                "_customer": customer.match.model_dump(exclude_none=True),
                "_order_verified": verified,
            }
        )
        resource = str(
            params.get("order_id")
            or params.get("purchase_reference")
            or "customer_orders"
        )
        resource_type = "order_issue" if operation == "orders.create_claim" else "order"
        return await actions.request(
            action_id=action_id,
            conversation_id=conversation_id,
            customer_ref=customer_ref,
            capability="orders",
            action_type=operation,
            risk=definition.risk,
            minimum_identity_level=IdentityLevel(definition.required_identity_level),
            tenant_policy=tenant_policy,
            assessment=customer.assessment,
            authorization=AuthorizationDecision(
                tenant_id=self.context.tenant_id,
                customer_ref=customer_ref,
                resource_type=resource_type,
                resource_id=resource,
                action=operation,
                allowed=True,
                reason_code="customer_reported_issue"
                if resource_type == "order_issue" and not verified
                else "verified_order_customer",
            ),
            resource_type=resource_type,
            resource_id=resource,
            parameters=params,
            approval_route_ref=binding.approval_route_ref
            if requirement.approval_required
            else None,
            connector_binding_id=binding_id,
            connector_name=binding.connector,
            requested_at=self.now(),
        )

    async def _provider(
        self,
        binding: OrdersBinding,
        operation: str,
        params: dict[str, object],
        *,
        action_id: UUID | None = None,
    ) -> ConnectorResult:
        try:
            return await self.connectors(binding).execute(
                ConnectorRequest(
                    tenant_id=self.context.tenant_id,
                    binding_id=binding.binding_id,
                    operation=operation,
                    arguments=params,
                    idempotency_key=str(action_id) if action_id else None,
                )
            )
        except Exception:
            return ConnectorResult(
                operation=operation,
                status="UNCERTAIN" if operation in WRITES else "FAILED",
                error_code="order_provider_unavailable",
            )

    async def _check_evidence(self, customer_ref: str, draft: IssueDraft) -> None:
        for evidence_id in draft.evidence_ids:
            if not await self.evidence.allowed(
                context=self.context, customer_ref=customer_ref, evidence_id=evidence_id
            ):
                raise OrderUnavailable("order_evidence_unavailable")

    @asynccontextmanager
    async def _receipts(self) -> AsyncIterator[OrderReceipts]:
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            yield OrderReceipts(session, self.context)

    async def execute_authorized(self, action: ActionRecord) -> ConnectorResult:
        if action.action_type in READS:
            return await self._perform(action)
        # Independent transaction: crash/outer Action rollback cannot erase claim.
        async with self.sessions.begin() as guard:
            key = int.from_bytes(
                hashlib.sha256(
                    f"orders:{self.context.tenant_id}:{action.id}".encode()
                ).digest()[:8],
                "big",
                signed=True,
            )
            await guard.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": key}
            )
            async with self._receipts() as receipts:
                prior = await receipts.claim_or_replay(action)
                if prior is not None:
                    return prior
            try:
                result = await self._perform(action)
                reject_sensitive_fields(result.data)
            except OrderUnavailable as error:
                result = ConnectorResult(
                    operation=action.action_type,
                    status="REJECTED",
                    error_code=str(error),
                )
            except Exception:
                result = ConnectorResult(
                    operation=action.action_type,
                    status="UNCERTAIN",
                    error_code="order_execution_unconfirmed",
                )
            async with self._receipts() as receipts:
                await receipts.finish(action, result)
                await AuditService(receipts.session).record(
                    context=self.context,
                    event_type="orders.operation",
                    entity_type="action",
                    entity_id=action.id,
                    payload={"operation": action.action_type, "status": result.status},
                )
            return result

    async def _perform(self, action: ActionRecord) -> ConnectorResult:
        binding = self.binding(action.connector_binding_id)
        if binding.digest != action.parameters.get(
            "_configuration_digest"
        ) or not self.supports(binding, action.action_type):
            raise OrderUnavailable("order_configuration_changed")
        params = {
            key: value
            for key, value in action.parameters.items()
            if not key.startswith("_")
        }
        customer = await self.customer(
            action.customer_ref,
            binding.binding_id,
            action.id,
            int(action.required_identity_level),
        )
        if customer.match.model_dump(exclude_none=True) != action.parameters.get(
            "_customer"
        ):
            raise OrderUnavailable("order_customer_binding_changed")
        if action.action_type == "orders.create_claim":
            draft = IssueDraft.model_validate(params)
            await self._check_evidence(action.customer_ref, draft)
            verified = False
            if draft.order_id:
                live = await self._provider(
                    binding,
                    READS[1],
                    {
                        "order_id": draft.order_id,
                        "customer": customer.match.model_dump(exclude_none=True),
                    },
                )
                verified = live.status == "SUCCEEDED"
                if not verified and draft.issue_type != "missing_order":
                    raise OrderUnavailable(safe_reason(live))
            intake = case_intake(
                context=self.context,
                conversation_id=action.conversation_id,
                customer_ref=action.customer_ref,
                binding_id=binding.binding_id,
                action_id=action.id,
                draft=draft,
                order_verified=verified,
            )
            try:
                receipt = await self.cases.create_or_update(
                    context=self.context, intake=intake
                )
            except CasesUnavailable:
                raise OrderUnavailable("case_creation_unavailable") from None
            if (receipt.tenant_id, receipt.customer_ref, receipt.deduplication_key) != (
                self.context.tenant_id,
                action.customer_ref,
                intake.deduplication_key,
            ):
                raise RuntimeError("invalid_case_receipt")
            return ConnectorResult(
                operation=action.action_type,
                status="SUCCEEDED",
                data={
                    "case_id": str(receipt.case_id),
                    "case_status": receipt.status,
                    "reused": receipt.reused,
                    "resolution_promised": False,
                },
            )
        params["customer"] = customer.match.model_dump(exclude_none=True)
        return await self._provider(
            binding, action.action_type, params, action_id=action.id
        )


class OrdersActionConnector:
    def __init__(self, orders: OrdersService) -> None:
        self.orders = orders
        self._permits: dict[str, ActionRecord] = {}

    def is_safe_read(self, operation: str) -> bool:
        return operation in READS

    async def revalidate(self, action: ActionRecord) -> PreconditionDecision:
        self._permits.pop(str(action.id), None)
        try:
            binding = self.orders.binding(action.connector_binding_id)
            definition = DEFINITIONS[action.action_type]
            customer = await self.orders.customer(
                action.customer_ref,
                binding.binding_id,
                action.id,
                max(
                    int(action.required_identity_level),
                    definition.required_identity_level,
                ),
            )
            confirmed = (
                action.confirmed_at is not None
                and action.confirmation_digest
                == hashlib.sha256(
                    f"{action.id}:{action.customer_ref}:{action.parameter_digest}:confirmed".encode()
                ).hexdigest()
            )
            approved = (
                action.state == "AWAITING_APPROVAL"
                and action.approval_required
                and bool(action.approval_reference)
                and action.approved_at is not None
            )
            valid = (
                action.tenant_id == self.orders.context.tenant_id
                and action.capability == "orders"
                and action.connector_name == binding.connector
                and action.risk == definition.risk
                and binding.digest == action.parameters.get("_configuration_digest")
                and customer.match.model_dump(exclude_none=True)
                == action.parameters.get("_customer")
                and (not action.confirmation_required or confirmed)
                and (
                    not definition.requires_confirmation or action.confirmation_required
                )
                and (not definition.requires_approval or action.approval_required)
                and (
                    (action.state == "CONFIRMED" and not action.approval_required)
                    or approved
                )
                and action_gate(
                    action.action_type,
                    identity_level=int(customer.assessment.achieved_level),
                    confirmed=confirmed,
                    approved=approved,
                    supported=self.orders.supports(binding, action.action_type),
                )
                == "READY"
            )
            if not valid:
                raise OrderUnavailable("order_action_not_authorized")
        except (OrderUnavailable, KeyError, ValidationError) as error:
            return PreconditionDecision(
                valid=False,
                reason_code=str(error)
                if isinstance(error, OrderUnavailable)
                else "order_action_not_authorized",
            )
        self._permits[str(action.id)] = action
        return PreconditionDecision(valid=True, reason_code="ready")

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        action = self._permits.get(request.idempotency_key or "")
        if (
            action is None
            or action.tenant_id != request.tenant_id
            or action.connector_binding_id != request.binding_id
            or action.action_type != request.operation
            or action.parameter_digest
            != NormalizedParameters.from_value(request.arguments).digest
        ):
            return ConnectorResult(
                operation=request.operation,
                status="REJECTED",
                error_code="order_action_not_authorized",
            )
        if request.operation not in READS:
            self._permits.pop(str(action.id), None)
        return await self.orders.execute_authorized(action)


def safe_reason(result: ConnectorResult) -> str:
    return (
        result.error_code
        if result.error_code
        in {
            "order_not_found",
            "stale_version",
            "order_not_mutable",
            "insufficient_scope",
            "operation_not_allowed",
            "integration_not_connected",
        }
        else "order_read_unavailable"
    )


def customer_message(*, state: str, operation: str, language: str) -> str:
    spanish = language == "es"
    if state == "SUCCEEDED":
        if operation == WRITES[3]:
            return (
                "La solicitud de cancelación quedó registrada; el pedido aún no está cancelado."
                if spanish
                else "The cancellation request was recorded; the order has not been cancelled."
            )
        if operation == "orders.create_claim":
            return (
                "El caso quedó registrado para revisión; no implica aceptación ni reembolso."
                if spanish
                else "The case was recorded for review; acceptance or a refund has not been promised."
            )
        return (
            "La consulta se completó."
            if spanish and operation in READS
            else "The lookup completed."
            if operation in READS
            else "El cambio quedó registrado."
            if spanish
            else "The change was recorded."
        )
    if state == "UNCERTAIN":
        return (
            "No pude confirmar el resultado. Se necesita revisión; no repetiré el cambio automáticamente."
            if spanish
            else "The outcome could not be confirmed. Review is needed; the change will not be repeated automatically."
        )
    return (
        "Esta operación de pedidos no está disponible ahora. Puedo ayudarte con otras consultas u ofrecer revisión humana."
        if spanish
        else "This order operation is unavailable right now. I can help with other questions or offer human review."
    )
