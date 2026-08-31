from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.actions.models import (
    ActionOutcome,
    ActionRecord,
    ActionState,
    NormalizedParameters,
    PreconditionDecision,
)
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.actions.state_machine import ActionStateMachine
from agents_factory.modules.identity.models import (
    AuthorizationDecision,
    IdentityAssessment,
    IdentityLevel,
)
from agents_factory.modules.integrations.contracts import (
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.policies.evaluator import ActionPolicyEvaluator
from agents_factory.modules.policies.models import RiskLevel, TenantActionPolicy
from agents_factory.modules.runtime.contracts import reject_sensitive_fields


class IdentityActionGuard(Protocol):
    def require_for_action(
        self,
        *,
        assessment: IdentityAssessment,
        required_level: IdentityLevel,
        authorization: AuthorizationDecision,
        action: str,
        resource_type: str,
        resource_id: str,
    ) -> None: ...


class ActionConnector(Protocol):
    def is_safe_read(self, operation: str) -> bool: ...

    async def revalidate(self, action: ActionRecord) -> PreconditionDecision: ...

    async def execute(self, request: ConnectorRequest) -> ConnectorResult: ...


class ApprovalVerifier(Protocol):
    async def verify(
        self,
        *,
        route_ref: str,
        approval_reference: str,
        action_id: UUID,
        parameter_digest: str,
    ) -> bool: ...


ResultBuilder = Callable[
    [ActionRecord, ActionState, dict[str, object]], dict[str, object]
]


class ActionService:
    def __init__(
        self,
        *,
        context: TenantContext,
        repository: ActionRepository,
        identity_guard: IdentityActionGuard,
        connector: ActionConnector,
        approval_verifier: ApprovalVerifier,
        audit: AuditService,
        outbox: OutboxService,
        confirmation_ttl: timedelta = timedelta(minutes=15),
        result_builder: ResultBuilder | None = None,
    ) -> None:
        self._context = context
        self._repository = repository
        self._identity_guard = identity_guard
        self._connector = connector
        self._approval_verifier = approval_verifier
        self._audit = audit
        self._outbox = outbox
        self._policy = ActionPolicyEvaluator()
        self._machine = ActionStateMachine()
        self._confirmation_ttl = confirmation_ttl
        self._result_builder = result_builder

    async def request(
        self,
        *,
        action_id: UUID,
        conversation_id: UUID,
        customer_ref: str,
        capability: str,
        action_type: str,
        risk: RiskLevel,
        minimum_identity_level: IdentityLevel,
        tenant_policy: TenantActionPolicy | None,
        assessment: IdentityAssessment,
        authorization: AuthorizationDecision,
        resource_type: str,
        resource_id: str,
        parameters: dict[str, object],
        approval_route_ref: str | None,
        connector_binding_id: UUID,
        connector_name: str,
        requested_at: datetime | None = None,
    ) -> ActionRecord:
        now = requested_at or datetime.now(UTC)
        reject_sensitive_fields(parameters)
        normalized = NormalizedParameters.from_value(parameters)
        requirement = self._policy.evaluate(
            risk=risk,
            minimum_identity_level=minimum_identity_level,
            tenant_policy=tenant_policy,
        )
        if requirement.approval_required and not approval_route_ref:
            raise _action_error(
                code="approval_route_required",
                title="Approval Route Required",
                detail="A high-risk action requires a configured approval route.",
            )
        action, created = await self._repository.create(
            action_id=action_id,
            conversation_id=conversation_id,
            customer_ref=customer_ref,
            capability=capability,
            action_type=action_type,
            risk=risk,
            requirement=requirement,
            achieved_identity_level=assessment.achieved_level,
            parameters=normalized,
            confirmation_expires_at=(
                now + self._confirmation_ttl
                if requirement.confirmation_required
                else None
            ),
            approval_route_ref=approval_route_ref,
            connector_binding_id=connector_binding_id,
            connector_name=connector_name,
            created_at=now,
        )
        if not created:
            self._assert_same_request(
                existing=action,
                conversation_id=conversation_id,
                customer_ref=customer_ref,
                action_type=action_type,
                parameter_digest=normalized.digest,
                connector_binding_id=connector_binding_id,
            )
            return action
        try:
            self._identity_guard.require_for_action(
                assessment=assessment,
                required_level=requirement.identity_level,
                authorization=authorization,
                action=action_type,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        except DomainError:
            await self._repository.transition(
                action=action,
                target="REJECTED",
                event_type="action.identity_or_authorization_rejected",
                payload={"reason_code": "identity_or_authorization_failed"},
                changed_at=now,
            )
            raise
        action = await self._transition(
            action,
            "IDENTITY_VERIFIED",
            "action.identity_verified",
            now,
        )
        target: ActionState = (
            "AWAITING_CONFIRMATION"
            if requirement.confirmation_required
            else "CONFIRMED"
        )
        action = await self._transition(action, target, f"action.{target.lower()}", now)
        if target == "CONFIRMED" and requirement.approval_required:
            action = await self._transition(
                action,
                "AWAITING_APPROVAL",
                "action.awaiting_approval",
                now,
            )
        return action

    async def confirm(
        self,
        *,
        action_id: UUID,
        parameter_digest: str,
        customer_ref: str,
        confirmed_at: datetime | None = None,
    ) -> ActionRecord:
        now = confirmed_at or datetime.now(UTC)
        action = await self._required_locked(action_id)
        if action.state != "AWAITING_CONFIRMATION":
            raise _invalid_state(action.state)
        if customer_ref != action.customer_ref:
            raise _action_error(
                code="action_confirmation_mismatch",
                title="Action Confirmation Mismatch",
                detail="Confirmation did not match the requesting customer.",
            )
        if (
            action.confirmation_expires_at is None
            or now >= action.confirmation_expires_at
        ):
            await self._repository.transition(
                action=action,
                target="EXPIRED",
                event_type="action.confirmation_expired",
                payload={},
                changed_at=now,
            )
            raise _action_error(
                code="action_confirmation_expired",
                title="Action Confirmation Expired",
                detail="The action must be requested and reviewed again.",
            )
        if parameter_digest != action.parameter_digest:
            await self._repository.transition(
                action=action,
                target="REJECTED",
                event_type="action.confirmation_digest_mismatch",
                payload={},
                changed_at=now,
            )
            raise _action_error(
                code="action_confirmation_mismatch",
                title="Action Confirmation Mismatch",
                detail="Confirmation did not match the exact requested parameters.",
            )
        evidence_digest = hashlib.sha256(
            (
                f"{action.id}:{action.customer_ref}:{action.parameter_digest}:confirmed"
            ).encode()
        ).hexdigest()
        action = await self._repository.confirm(
            action=action,
            confirmation_digest=evidence_digest,
            confirmed_at=now,
        )
        if action.approval_required:
            action = await self._transition(
                action,
                "AWAITING_APPROVAL",
                "action.awaiting_approval",
                now,
            )
        return action

    async def approve_reference(
        self,
        *,
        action_id: UUID,
        parameter_digest: str,
        approval_reference: str,
        approved_at: datetime | None = None,
    ) -> ActionRecord:
        now = approved_at or datetime.now(UTC)
        action = await self._required_locked(action_id)
        if (
            action.state != "AWAITING_APPROVAL"
            or not action.approval_required
            or not action.approval_route_ref
            or action.parameter_digest != parameter_digest
        ):
            raise _action_error(
                code="invalid_action_approval",
                title="Invalid Action Approval",
                detail="Approval must match the configured route and exact parameters.",
            )
        assert action.approval_route_ref is not None
        verified = await self._approval_verifier.verify(
            route_ref=action.approval_route_ref,
            approval_reference=approval_reference,
            action_id=action.id,
            parameter_digest=action.parameter_digest,
        )
        if not verified:
            raise _action_error(
                code="invalid_action_approval",
                title="Invalid Action Approval",
                detail="Approval evidence could not be verified.",
            )
        return await self._repository.approve(
            action=action,
            approval_reference=approval_reference,
            approved_at=now,
        )

    async def execute(
        self, *, action_id: UUID, executed_at: datetime | None = None
    ) -> ActionOutcome:
        action = await self.prepare_execution(
            action_id=action_id, executed_at=executed_at
        )
        if self._machine.is_terminal(action.state):
            return _outcome(action)
        result = await self.invoke_connector(action)
        return await self.complete_execution(
            action_id=action.id, result=result, finished_at=executed_at
        )

    async def prepare_execution(
        self, *, action_id: UUID, executed_at: datetime | None = None
    ) -> ActionRecord:
        """Revalidate and claim; durable coordinators commit before provider writes."""
        now = executed_at or datetime.now(UTC)
        action = await self._required_locked(action_id)
        if self._machine.is_terminal(action.state):
            return action
        if action.state == "EXECUTING":
            action = await self._finish(
                action=action,
                target="UNCERTAIN",
                result_payload={"reason_code": "interrupted_execution"},
                finished_at=now,
            )
            await self._record_final(action)
            return action
        ready = action.state == "CONFIRMED" and not action.approval_required
        approved = (
            action.state == "AWAITING_APPROVAL"
            and action.approval_required
            and action.approval_reference is not None
            and action.approved_at is not None
        )
        if not (ready or approved):
            raise _invalid_state(action.state)

        if approved and not await self._approval_verifier.verify(
            route_ref=action.approval_route_ref or "",
            approval_reference=action.approval_reference or "",
            action_id=action.id,
            parameter_digest=action.parameter_digest,
        ):
            action = await self._finish(
                action=action,
                target="REJECTED",
                result_payload={"reason_code": "approval_no_longer_valid"},
                finished_at=now,
            )
            await self._record_final(action)
            return action
        try:
            precondition = await self._connector.revalidate(action)
        except Exception:
            precondition = PreconditionDecision(
                valid=False, reason_code="connector_unavailable"
            )
        await self._audit.record(
            context=self._context,
            event_type="action.revalidated",
            entity_type="action",
            entity_id=action.id,
            payload={
                "valid": precondition.valid,
                "parameter_digest": action.parameter_digest,
            },
        )
        if not precondition.valid:
            action = await self._finish(
                action=action,
                target="REJECTED"
                if approved and precondition.reason_code != "connector_unavailable"
                else "FAILED",
                result_payload={"reason_code": precondition.reason_code},
                finished_at=now,
            )
            await self._record_final(action)
            return action

        # Revalidation may involve slow reads: do not execute an approval that
        # expired while those reads were in flight.
        if approved and not await self._approval_verifier.verify(
            route_ref=action.approval_route_ref or "",
            approval_reference=action.approval_reference or "",
            action_id=action.id,
            parameter_digest=action.parameter_digest,
        ):
            action = await self._finish(
                action=action,
                target="REJECTED",
                result_payload={"reason_code": "approval_no_longer_valid"},
                finished_at=now,
            )
            await self._record_final(action)
            return action
        return await self._repository.begin_execution(action=action, started_at=now)

    async def invoke_connector(self, action: ActionRecord) -> ConnectorResult:
        """Use the permit issued by prepare_execution, without holding a DB transaction."""
        safe_read = self._connector.is_safe_read(action.action_type)
        max_attempts = 2 if safe_read else 1
        final_result: ConnectorResult | None = None
        for attempt in range(max_attempts):
            try:
                final_result = await self._connector.execute(
                    ConnectorRequest(
                        tenant_id=self._context.tenant_id,
                        binding_id=action.connector_binding_id,
                        operation=action.action_type,
                        arguments=action.parameters,
                        idempotency_key=str(action.id),
                    )
                )
            except TimeoutError:
                if safe_read and attempt + 1 < max_attempts:
                    continue
                final_result = ConnectorResult(
                    operation=action.action_type,
                    status="FAILED" if safe_read else "UNCERTAIN",
                    error_code="connector_timeout",
                )
            except Exception:
                if safe_read and attempt + 1 < max_attempts:
                    continue
                final_result = ConnectorResult(
                    operation=action.action_type,
                    status="FAILED" if safe_read else "UNCERTAIN",
                    error_code="connector_error",
                )
            if final_result.status == "FAILED" and attempt + 1 < max_attempts:
                continue
            break
        assert final_result is not None
        return final_result

    async def complete_execution(
        self,
        *,
        action_id: UUID,
        result: ConnectorResult,
        finished_at: datetime | None = None,
    ) -> ActionOutcome:
        action = await self._required_locked(action_id)
        if self._machine.is_terminal(action.state):
            return _outcome(action)
        if action.state != "EXECUTING":
            raise _invalid_state(action.state)
        safe_read = self._connector.is_safe_read(action.action_type)
        final_result = result
        try:
            reject_sensitive_fields(final_result.data)
            safe_data = final_result.data
            target = _result_state(final_result)
        except ValueError:
            safe_data = {}
            target = "UNCERTAIN" if not safe_read else "FAILED"
            final_result = ConnectorResult(
                operation=action.action_type,
                status="UNCERTAIN" if not safe_read else "FAILED",
                error_code="connector_response_rejected",
            )
        payload: dict[str, object] = {
            "connector_status": final_result.status,
            "data": safe_data,
        }
        if final_result.error_code is not None:
            payload["error_code"] = final_result.error_code
        action = await self._finish(
            action=action,
            target=target,
            result_payload=payload,
            finished_at=finished_at or datetime.now(UTC),
        )
        await self._record_final(action)
        return _outcome(action)

    async def _finish(
        self,
        *,
        action: ActionRecord,
        target: ActionState,
        result_payload: dict[str, object],
        finished_at: datetime,
    ) -> ActionRecord:
        if self._result_builder is not None:
            result_payload = self._result_builder(action, target, result_payload)
        return await self._repository.finish(
            action=action,
            target=target,
            result_payload=result_payload,
            finished_at=finished_at,
        )

    async def _transition(
        self,
        action: ActionRecord,
        target: ActionState,
        event_type: str,
        changed_at: datetime,
    ) -> ActionRecord:
        self._machine.transition(action.state, target)
        return await self._repository.transition(
            action=action,
            target=target,
            event_type=event_type,
            payload={},
            changed_at=changed_at,
        )

    async def _required_locked(self, action_id: UUID) -> ActionRecord:
        action = await self._repository.get(action_id, lock=True)
        if action is None:
            raise _action_error(
                code="action_not_found",
                title="Action Not Found",
                detail="The requested action does not exist.",
                status=404,
            )
        return action

    async def _record_final(self, action: ActionRecord) -> None:
        await self._audit.record(
            context=self._context,
            event_type=f"action.{action.state.lower()}",
            entity_type="action",
            entity_id=action.id,
            payload={
                "conversation_id": str(action.conversation_id),
                "action_type": action.action_type,
                "risk": action.risk,
                "parameter_digest": action.parameter_digest,
                "state": action.state,
            },
        )
        await self._outbox.enqueue(
            context=self._context,
            idempotency_key=f"action.result:{action.id}:{action.state}",
            topic="action.result",
            payload={"action_id": str(action.id), "state": action.state},
        )

    def _assert_same_request(
        self,
        *,
        existing: ActionRecord,
        conversation_id: UUID,
        customer_ref: str,
        action_type: str,
        parameter_digest: str,
        connector_binding_id: UUID,
    ) -> None:
        if (
            existing.conversation_id,
            existing.customer_ref,
            existing.action_type,
            existing.parameter_digest,
            existing.connector_binding_id,
        ) != (
            conversation_id,
            customer_ref,
            action_type,
            parameter_digest,
            connector_binding_id,
        ):
            raise _action_error(
                code="action_idempotency_conflict",
                title="Action Idempotency Conflict",
                detail="The action ID is already bound to a different request.",
            )


def _result_state(result: ConnectorResult) -> ActionState:
    return cast(
        ActionState,
        {
            "SUCCEEDED": "SUCCEEDED",
            "REJECTED": "FAILED",
            "FAILED": "FAILED",
            "UNCERTAIN": "UNCERTAIN",
        }[result.status],
    )


def _outcome(action: ActionRecord) -> ActionOutcome:
    messages = {
        "SUCCEEDED": "La operación se completó correctamente.",
        "REJECTED": "La operación fue rechazada.",
        "FAILED": "No fue posible completar la operación.",
        "UNCERTAIN": (
            "No pude confirmar el resultado. Se requiere verificación segura "
            "o revisión de backoffice."
        ),
        "EXPIRED": "La solicitud venció y debe iniciarse nuevamente.",
        "HANDED_OFF": "La solicitud fue enviada para revisión humana.",
    }
    return ActionOutcome(
        action_id=action.id,
        state=action.state,
        customer_message=messages.get(action.state, "La acción continúa en proceso."),
        result=action.result,
    )


def _invalid_state(state: ActionState) -> DomainError:
    return _action_error(
        code="invalid_action_state",
        title="Invalid Action State",
        detail=f"The action cannot advance from {state}.",
    )


def _action_error(
    *, code: str, title: str, detail: str, status: int = 409
) -> DomainError:
    return DomainError(
        type=f"https://agents-factory.dev/problems/{code.replace('_', '-')}",
        title=title,
        status=status,
        detail=detail,
        code=code,
    )
