from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.actions.models import (
    ActionRecord,
    ActionState,
    NormalizedParameters,
    PreconditionDecision,
)
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.identity.models import (
    AuthorizationDecision,
    IdentityAssessment,
    IdentityLevel,
)
from agents_factory.modules.integrations.contracts import (
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.policies.models import ActionRequirement, RiskLevel


NOW = datetime(2026, 8, 29, 16, tzinfo=UTC)
TENANT_ID = UUID("10000000-0000-0000-0000-000000000015")
CONVERSATION_ID = UUID("20000000-0000-0000-0000-000000000015")
BINDING_ID = UUID("30000000-0000-0000-0000-000000000015")


class Guard:
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
        if (
            assessment.achieved_level < required_level
            or not authorization.allowed
            or authorization.action != action
            or authorization.resource_type != resource_type
            or authorization.resource_id != resource_id
        ):
            raise DomainError(
                type="test:not-authorized",
                title="Not authorized",
                status=403,
                detail="Denied.",
                code="action_not_authorized",
            )


class Store:
    def __init__(self) -> None:
        self.actions: dict[UUID, ActionRecord] = {}

    async def create(
        self,
        *,
        action_id: UUID,
        conversation_id: UUID,
        customer_ref: str,
        capability: str,
        action_type: str,
        risk: RiskLevel,
        requirement: ActionRequirement,
        achieved_identity_level: IdentityLevel,
        parameters: NormalizedParameters,
        confirmation_expires_at: datetime | None,
        approval_route_ref: str | None,
        connector_binding_id: UUID,
        connector_name: str,
        created_at: datetime,
    ) -> tuple[ActionRecord, bool]:
        if action_id in self.actions:
            return self.actions[action_id], False
        action = ActionRecord(
            id=action_id,
            tenant_id=TENANT_ID,
            conversation_id=conversation_id,
            customer_ref=customer_ref,
            capability=capability,
            action_type=action_type,
            risk=risk,
            required_identity_level=requirement.identity_level,
            achieved_identity_level=achieved_identity_level,
            parameters=parameters.value,
            parameter_digest=parameters.digest,
            confirmation_required=requirement.confirmation_required,
            confirmation_digest=None,
            confirmed_at=None,
            confirmation_expires_at=confirmation_expires_at,
            approval_required=requirement.approval_required,
            approval_route_ref=approval_route_ref,
            approval_reference=None,
            approved_at=None,
            connector_binding_id=connector_binding_id,
            connector_name=connector_name,
            state="REQUESTED",
            result={},
            execution_attempts=0,
            created_at=created_at,
            updated_at=created_at,
        )
        self.actions[action_id] = action
        return action, True

    async def get(self, action_id: UUID, *, lock: bool = False) -> ActionRecord | None:
        _ = lock
        return self.actions.get(action_id)

    async def transition(
        self,
        *,
        action: ActionRecord,
        target: ActionState,
        event_type: str,
        payload: dict[str, object],
        changed_at: datetime,
    ) -> ActionRecord:
        _ = (event_type, payload)
        updated = action.model_copy(update={"state": target, "updated_at": changed_at})
        self.actions[action.id] = updated
        return updated

    async def confirm(
        self,
        *,
        action: ActionRecord,
        confirmation_digest: str,
        confirmed_at: datetime,
    ) -> ActionRecord:
        updated = action.model_copy(
            update={
                "state": "CONFIRMED",
                "confirmation_digest": confirmation_digest,
                "confirmed_at": confirmed_at,
                "updated_at": confirmed_at,
            }
        )
        self.actions[action.id] = updated
        return updated

    async def approve(
        self,
        *,
        action: ActionRecord,
        approval_reference: str,
        approved_at: datetime,
    ) -> ActionRecord:
        updated = action.model_copy(
            update={
                "approval_reference": approval_reference,
                "approved_at": approved_at,
                "updated_at": approved_at,
            }
        )
        self.actions[action.id] = updated
        return updated

    async def begin_execution(
        self, *, action: ActionRecord, started_at: datetime
    ) -> ActionRecord:
        updated = action.model_copy(
            update={
                "state": "EXECUTING",
                "execution_attempts": action.execution_attempts + 1,
                "updated_at": started_at,
            }
        )
        self.actions[action.id] = updated
        return updated

    async def finish(
        self,
        *,
        action: ActionRecord,
        target: ActionState,
        result_payload: dict[str, object],
        finished_at: datetime,
    ) -> ActionRecord:
        updated = action.model_copy(
            update={
                "state": target,
                "result": result_payload,
                "updated_at": finished_at,
            }
        )
        self.actions[action.id] = updated
        return updated


class Connector:
    def __init__(
        self,
        results: list[ConnectorResult],
        *,
        safe_read: bool,
        precondition_valid: bool = True,
    ) -> None:
        self.results = results
        self.safe_read = safe_read
        self.precondition_valid = precondition_valid
        self.calls: list[ConnectorRequest] = []

    def is_safe_read(self, operation: str) -> bool:
        _ = operation
        return self.safe_read

    async def revalidate(self, action: ActionRecord) -> PreconditionDecision:
        _ = action
        return PreconditionDecision(
            valid=self.precondition_valid,
            reason_code="current" if self.precondition_valid else "state_changed",
        )

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        self.calls.append(request)
        return self.results.pop(0)


class Recorder:
    async def record(self, **kwargs: object) -> None:
        _ = kwargs

    async def enqueue(self, **kwargs: object) -> None:
        _ = kwargs


class ApprovalGuard:
    async def verify(
        self,
        *,
        route_ref: str,
        approval_reference: str,
        action_id: UUID,
        parameter_digest: str,
    ) -> bool:
        _ = (action_id, parameter_digest)
        return route_ref == "route-1" and approval_reference == "approval-1"


def context() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        actor_id=None,
        actor_type="system",
        correlation_id=uuid4(),
    )


def assessment(level: IdentityLevel = IdentityLevel.LEVEL_3) -> IdentityAssessment:
    return IdentityAssessment(
        tenant_id=TENANT_ID,
        customer_ref="customer",
        achieved_level=level,
        evidence_ids=(uuid4(),),
        assessed_at=NOW,
    )


def authorization(action_type: str, *, allowed: bool = True) -> AuthorizationDecision:
    return AuthorizationDecision(
        tenant_id=TENANT_ID,
        customer_ref="customer",
        resource_type="order",
        resource_id="order-1",
        action=action_type,
        allowed=allowed,
        reason_code="owner" if allowed else "not_owner",
    )


def service(store: Store, connector: Connector) -> ActionService:
    recorder = Recorder()
    return ActionService(
        context=context(),
        repository=cast(ActionRepository, store),
        identity_guard=Guard(),
        connector=connector,
        approval_verifier=ApprovalGuard(),
        audit=cast(AuditService, recorder),
        outbox=cast(OutboxService, recorder),
    )


async def request(
    actions: ActionService,
    *,
    action_id: UUID,
    risk: RiskLevel,
    action_type: str,
    approval_route_ref: str | None,
    parameters: dict[str, object] | None = None,
) -> ActionRecord:
    return await actions.request(
        action_id=action_id,
        conversation_id=CONVERSATION_ID,
        customer_ref="customer",
        capability="orders",
        action_type=action_type,
        risk=risk,
        minimum_identity_level=IdentityLevel.LEVEL_1,
        tenant_policy=None,
        assessment=assessment(),
        authorization=authorization(action_type),
        resource_type="order",
        resource_id="order-1",
        parameters=parameters or {"order_id": "order-1"},
        approval_route_ref=approval_route_ref,
        connector_binding_id=BINDING_ID,
        connector_name="woocommerce",
        requested_at=NOW,
    )


@pytest.mark.asyncio
async def test_medium_action_cannot_bypass_exact_confirmation() -> None:
    store = Store()
    connector = Connector([], safe_read=False)
    actions = service(store, connector)
    action_id = uuid4()
    action = await request(
        actions,
        action_id=action_id,
        risk="MEDIUM",
        action_type="orders.update_address",
        approval_route_ref=None,
    )
    assert action.state == "AWAITING_CONFIRMATION"

    with pytest.raises(DomainError):
        await actions.execute(action_id=action_id, executed_at=NOW)
    with pytest.raises(DomainError):
        await actions.confirm(
            action_id=action_id,
            parameter_digest="f" * 64,
            customer_ref="customer",
            confirmed_at=NOW,
        )
    assert store.actions[action_id].state == "REJECTED"
    assert connector.calls == []


@pytest.mark.asyncio
async def test_expired_confirmation_requires_a_new_request() -> None:
    store = Store()
    actions = service(store, Connector([], safe_read=False))
    action_id = uuid4()
    action = await request(
        actions,
        action_id=action_id,
        risk="MEDIUM",
        action_type="orders.update_address",
        approval_route_ref=None,
    )

    with pytest.raises(DomainError) as expired:
        await actions.confirm(
            action_id=action_id,
            parameter_digest=action.parameter_digest,
            customer_ref="customer",
            confirmed_at=NOW.replace(minute=NOW.minute + 16),
        )

    assert expired.value.code == "action_confirmation_expired"
    assert store.actions[action_id].state == "EXPIRED"


@pytest.mark.asyncio
async def test_high_action_requires_route_confirmation_and_approval() -> None:
    store = Store()
    connector = Connector(
        [
            ConnectorResult(
                operation="orders.cancel",
                status="UNCERTAIN",
                error_code="provider_timeout",
            )
        ],
        safe_read=False,
    )
    actions = service(store, connector)
    with pytest.raises(DomainError) as missing_route:
        await request(
            actions,
            action_id=uuid4(),
            risk="HIGH",
            action_type="orders.cancel",
            approval_route_ref=None,
        )
    assert missing_route.value.code == "approval_route_required"

    action_id = uuid4()
    action = await request(
        actions,
        action_id=action_id,
        risk="HIGH",
        action_type="orders.cancel",
        approval_route_ref="route-1",
    )
    action = await actions.confirm(
        action_id=action_id,
        parameter_digest=action.parameter_digest,
        customer_ref="customer",
        confirmed_at=NOW,
    )
    assert action.state == "AWAITING_APPROVAL"
    with pytest.raises(DomainError):
        await actions.execute(action_id=action_id, executed_at=NOW)
    with pytest.raises(DomainError):
        await actions.approve_reference(
            action_id=action_id,
            parameter_digest=action.parameter_digest,
            approval_reference="forged-approval",
            approved_at=NOW,
        )
    await actions.approve_reference(
        action_id=action_id,
        parameter_digest=action.parameter_digest,
        approval_reference="approval-1",
        approved_at=NOW,
    )
    outcome = await actions.execute(action_id=action_id, executed_at=NOW)

    assert outcome.state == "UNCERTAIN"
    assert "completó correctamente" not in outcome.customer_message
    assert connector.calls[0].idempotency_key == str(action_id)


@pytest.mark.asyncio
async def test_duplicate_action_id_is_bound_to_canonical_parameters() -> None:
    store = Store()
    connector = Connector([], safe_read=True)
    actions = service(store, connector)
    action_id = uuid4()
    first = await request(
        actions,
        action_id=action_id,
        risk="LOW",
        action_type="orders.get_status",
        approval_route_ref=None,
        parameters={"order_id": "order-1", "include_items": True},
    )
    duplicate = await request(
        actions,
        action_id=action_id,
        risk="LOW",
        action_type="orders.get_status",
        approval_route_ref=None,
        parameters={"include_items": True, "order_id": "order-1"},
    )
    assert duplicate.id == first.id
    assert duplicate.parameter_digest == first.parameter_digest

    with pytest.raises(DomainError) as conflict:
        await request(
            actions,
            action_id=action_id,
            risk="LOW",
            action_type="orders.get_status",
            approval_route_ref=None,
            parameters={"order_id": "different"},
        )
    assert conflict.value.code == "action_idempotency_conflict"


@pytest.mark.asyncio
async def test_safe_read_retries_but_write_does_not_retry_blindly() -> None:
    read_store = Store()
    read_connector = Connector(
        [
            ConnectorResult(
                operation="orders.get_status", status="FAILED", error_code="temporary"
            ),
            ConnectorResult(
                operation="orders.get_status",
                status="SUCCEEDED",
                data={"status": "processing"},
            ),
        ],
        safe_read=True,
    )
    read_actions = service(read_store, read_connector)
    read_id = uuid4()
    await request(
        read_actions,
        action_id=read_id,
        risk="LOW",
        action_type="orders.get_status",
        approval_route_ref=None,
    )
    read_outcome = await read_actions.execute(action_id=read_id, executed_at=NOW)
    assert read_outcome.state == "SUCCEEDED"
    assert len(read_connector.calls) == 2

    write_store = Store()
    write_connector = Connector(
        [
            ConnectorResult(
                operation="orders.update_address",
                status="UNCERTAIN",
                error_code="timeout",
            )
        ],
        safe_read=False,
    )
    write_actions = service(write_store, write_connector)
    write_id = uuid4()
    action = await request(
        write_actions,
        action_id=write_id,
        risk="MEDIUM",
        action_type="orders.update_address",
        approval_route_ref=None,
    )
    await write_actions.confirm(
        action_id=write_id,
        parameter_digest=action.parameter_digest,
        customer_ref="customer",
        confirmed_at=NOW,
    )
    write_outcome = await write_actions.execute(action_id=write_id, executed_at=NOW)
    assert write_outcome.state == "UNCERTAIN"
    assert len(write_connector.calls) == 1


@pytest.mark.asyncio
async def test_changed_precondition_blocks_execution() -> None:
    store = Store()
    connector = Connector([], safe_read=True, precondition_valid=False)
    actions = service(store, connector)
    action_id = uuid4()
    await request(
        actions,
        action_id=action_id,
        risk="LOW",
        action_type="orders.get_status",
        approval_route_ref=None,
    )

    outcome = await actions.execute(action_id=action_id, executed_at=NOW)

    assert outcome.state == "FAILED"
    assert outcome.result == {"reason_code": "state_changed"}
    assert connector.calls == []
