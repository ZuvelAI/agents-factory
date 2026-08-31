"""Backend-only approval execution. No model or provider credentials are involved here."""

from collections.abc import Callable, Mapping
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from agents_factory.modules.actions.models import (
    ActionRecord,
    ActionState,
    NormalizedParameters,
)
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.actions.service import ActionConnector, ActionService
from agents_factory.modules.actions.state_machine import ActionStateMachine
from agents_factory.modules.approvals.repository import ApprovalRepository
from agents_factory.modules.approvals.result_schema import (
    DecisionResult,
    execution_result,
)
from agents_factory.modules.approvals.service import (
    PersistedApprovalVerifier,
    require_backend,
)
from agents_factory.modules.identity.models import (
    IdentityAssessment,
    AuthorizationDecision,
    IdentityLevel,
)
from agents_factory.modules.runtime.turn_service import AgentSpecProvider
from agents_factory.modules.whatsapp.template_service import TemplateService


class ExecutionOnlyIdentityGuard:
    def require_for_action(
        self,
        *,
        assessment: IdentityAssessment,
        required_level: IdentityLevel,
        authorization: AuthorizationDecision,
        action: str,
        resource_type: str,
        resource_id: str,
    ) -> None:
        raise RuntimeError("approval_worker_cannot_request_actions")


@dataclass(frozen=True)
class ApprovalNotificationBinding:
    template_name: str
    language: str = "es"


class ApprovalExecutionService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        agent_specs: Callable[[AsyncSession, TenantContext], AgentSpecProvider],
        connectors: Callable[[TenantContext, ActionRecord], ActionConnector],
        notifications: Mapping[UUID, ApprovalNotificationBinding],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        # Factories reload trusted tenant bindings, not a connector/model name from a job.
        self.sessions, self.agent_specs, self.connectors = (
            sessions,
            agent_specs,
            connectors,
        )
        self.notifications = dict(notifications)
        self.now = now or (lambda: datetime.now(UTC))

    async def execute(
        self, *, context: TenantContext, action_id: UUID
    ) -> DecisionResult:
        require_backend(context)
        # Serialize duplicates (including callers outside the queue runner).
        # Only this advisory mutex spans I/O; entity transactions stay short.
        key = int.from_bytes(
            hashlib.sha256(
                f"approval-execution:{context.tenant_id}:{action_id}".encode()
            ).digest()[:8],
            "big",
            signed=True,
        )
        async with self.sessions.begin() as guard:
            await guard.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": key}
            )
            return await self._execute(context=context, action_id=action_id)

    async def _execute(
        self, *, context: TenantContext, action_id: UUID
    ) -> DecisionResult:
        async with self.sessions.begin() as session:
            await self._scope(session, context)
            repository = ActionRepository(session, context)
            action = await repository.get(action_id, lock=True)
            if action is None or not action.approval_required:
                raise ValueError("approval_action_unavailable")
            approvals = ApprovalRepository(session, context)
            request = await approvals.request(action_id=action.id)
            if request is None:
                raise ValueError("approval_request_unavailable")
            route = await approvals.route(route_id=request.route_id, lock=" FOR SHARE")
            request = await approvals.request(request_id=request.id, locked=True)
            assert request is not None
            decision = await approvals.decision(request.id)
            if ActionStateMachine().is_terminal(action.state):
                return await self._queue_result(session, context, action, request.id)
            if decision is None or decision.decision != "APPROVE":
                raise ValueError("approval_decision_unavailable")

            if action.state == "EXECUTING":
                action = await repository.finish(
                    action=action,
                    target="UNCERTAIN",
                    finished_at=self.now(),
                    result_payload={
                        "reason_code": "interrupted_execution",
                        "approval_request_id": str(request.id),
                        "approval_reference": str(decision.id),
                        "decision_result": DecisionResult.for_reason(
                            "outcome_unknown"
                        ).model_dump(mode="json"),
                    },
                )
                return await self._queue_result(session, context, action, request.id)

            spec = await self.agent_specs(session, context).get_active(
                tenant_id=context.tenant_id
            )
            metadata: dict[str, object] = {
                "approval_request_id": str(request.id),
                "approval_reference": str(decision.id),
                "agent_spec_digest": spec.digest if spec else None,
            }

            def build_result(
                record: ActionRecord, state: ActionState, payload: dict[str, object]
            ) -> dict[str, object]:
                result = execution_result(
                    operation=record.action_type, state=state, payload=payload
                )
                return {
                    **payload,
                    **metadata,
                    "decision_result": result.model_dump(mode="json"),
                }

            reason: str | None = None
            if request.expires_at <= self.now():
                reason = "approval_expired"
            elif (
                request.state != "APPROVED"
                or route is None
                or not route.configuration.enabled
                or route.digest != request.route_digest
                or route.configuration.ref != action.approval_route_ref
                or route.configuration.action != action.action_type
                or route.configuration.capability != action.capability
                or request.parameter_digest != action.parameter_digest
                or decision.parameter_digest != action.parameter_digest
                or decision.action_id != action.id
                or action.parameter_digest
                != NormalizedParameters.from_value(action.parameters).digest
                or spec is None
                or not spec.active
                or spec.tenant_id != context.tenant_id
                or action.capability not in spec.active_capabilities
                or action.action_type not in spec.permitted_tools
            ):
                reason = "approval_no_longer_valid"
            if reason is not None:
                state: ActionState = (
                    "EXPIRED" if reason == "approval_expired" else "REJECTED"
                )
                action = await repository.finish(
                    action=action,
                    target=state,
                    result_payload=build_result(action, state, {"reason_code": reason}),
                    finished_at=self.now(),
                )
                return await self._queue_result(session, context, action, request.id)

            try:
                connector = self.connectors(context, action)
            except Exception:
                action = await repository.finish(
                    action=action,
                    target="FAILED",
                    finished_at=self.now(),
                    result_payload=build_result(
                        action, "FAILED", {"reason_code": "connector_unavailable"}
                    ),
                )
                return await self._queue_result(session, context, action, request.id)
            await AuditService(session).record(
                context=context,
                event_type="approval.execution_validated",
                entity_type="action",
                entity_id=action.id,
                payload={
                    **metadata,
                    "parameter_digest": action.parameter_digest,
                    "connector_binding_id": str(action.connector_binding_id),
                },
            )
            actions = ActionService(
                context=context,
                repository=repository,
                identity_guard=ExecutionOnlyIdentityGuard(),
                connector=connector,
                approval_verifier=PersistedApprovalVerifier(
                    self.sessions, context, now=self.now
                ),
                audit=AuditService(session),
                outbox=OutboxService(session),
                result_builder=build_result,
            )
            if (
                action.state == "AWAITING_APPROVAL"
                and action.approval_reference is None
            ):
                await actions.approve_reference(
                    action_id=action.id,
                    parameter_digest=action.parameter_digest,
                    approval_reference=str(decision.id),
                    approved_at=decision.decided_at,
                )
            action = await actions.prepare_execution(
                action_id=action.id, executed_at=self.now()
            )
            if ActionStateMachine().is_terminal(action.state):
                return await self._queue_result(session, context, action, request.id)
        # EXECUTING and approval evidence are committed before any native write.
        result = await actions.invoke_connector(action)
        # A malformed successful cancellation receipt is not evidence of success.
        if result.status == "SUCCEEDED" and (
            result.operation != action.action_type
            or action.action_type
            in {
                "orders.request_order_cancellation",
                "appointments.request_cancellation",
            }
            and result.data.get("cancellation_executed") is not False
        ):
            from agents_factory.modules.integrations.contracts import ConnectorResult

            result = ConnectorResult(
                operation=action.action_type,
                status="UNCERTAIN",
                error_code="invalid_execution_receipt",
            )
        async with self.sessions.begin() as session:
            await self._scope(session, context)
            actions = ActionService(
                context=context,
                repository=ActionRepository(session, context),
                identity_guard=ExecutionOnlyIdentityGuard(),
                connector=connector,
                approval_verifier=PersistedApprovalVerifier(
                    self.sessions, context, now=self.now
                ),
                audit=AuditService(session),
                outbox=OutboxService(session),
                result_builder=build_result,
            )
            await actions.complete_execution(
                action_id=action.id, result=result, finished_at=self.now()
            )
            final = await ActionRepository(session, context).get(action.id)
            assert final is not None
            return await self._queue_result(session, context, final, request.id)

    async def _queue_result(
        self,
        session: AsyncSession,
        context: TenantContext,
        action: ActionRecord,
        request_id: UUID,
    ) -> DecisionResult:
        result = DecisionResult.model_validate(action.result["decision_result"])
        job = await OutboxService(session).enqueue(
            context=context,
            idempotency_key=f"approvals.result:{action.id}",
            topic="approvals.result",
            payload={
                "aggregate_id": str(action.id),
                "approval_request_id": str(request_id),
            },
        )
        await AuditService(session).record(
            context=context,
            event_type="approval.result_queued",
            entity_type="action",
            entity_id=action.id,
            payload={
                "approval_request_id": str(request_id),
                "notification_job_id": str(job.id),
                "parameter_digest": action.parameter_digest,
                "reason_code": result.reason_code,
            },
        )
        return result

    async def notify(self, *, context: TenantContext, action_id: UUID) -> UUID | None:
        require_backend(context)
        async with self.sessions.begin() as session:
            await self._scope(session, context)
            action = await ActionRepository(session, context).get(action_id)
            if (
                action is None
                or not action.approval_required
                or not ActionStateMachine().is_terminal(action.state)
            ):
                raise ValueError("approval_result_unavailable")
            result = DecisionResult.model_validate(action.result["decision_result"])
            conversation = (
                (
                    await session.execute(
                        text(
                            "SELECT whatsapp_account_id, customer_wa_id, control_state, state_version FROM public.conversations WHERE tenant_id=:tenant AND id=:id"
                        ),
                        {"tenant": context.tenant_id, "id": action.conversation_id},
                    )
                )
                .mappings()
                .one()
            )
            if conversation["control_state"] != "AI_ACTIVE":
                await OutboxService(session).enqueue(
                    context=context,
                    idempotency_key=f"approvals.result.held:{action.id}:{conversation['state_version']}",
                    topic="approvals.result.held",
                    payload={"aggregate_id": str(action.id)},
                )
                return None
        binding = self.notifications.get(context.tenant_id)
        if binding is None:
            raise ValueError("approval_notification_not_configured")
        # TemplateService rechecks conversation authority under its own lock.
        outbound_id = await TemplateService(
            session_factory=self.sessions, context=context
        ).prepare_proactive(
            whatsapp_account_id=conversation["whatsapp_account_id"],
            recipient_wa_id=conversation["customer_wa_id"],
            template_name=binding.template_name,
            language=binding.language,
            variables={
                "request_id": str(action.id),
                "result": result.customer_safe_explanation,
            },
            idempotency_key=f"approvals.result:{action.id}",
            conversation_id=action.conversation_id,
        )
        async with self.sessions.begin() as session:
            await self._scope(session, context)
            await AuditService(session).record(
                context=context,
                event_type="approval.customer_notification_prepared",
                entity_type="action",
                entity_id=action.id,
                payload={
                    "outbound_message_id": str(outbound_id),
                    "reason_code": result.reason_code,
                },
            )
        return outbound_id

    @staticmethod
    async def _scope(session: AsyncSession, context: TenantContext) -> None:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await set_tenant_context(session, context.tenant_id)
