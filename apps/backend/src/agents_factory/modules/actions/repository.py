from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.actions.models import (
    ActionRecord,
    ActionState,
    NormalizedParameters,
)
from agents_factory.modules.identity.models import IdentityLevel
from agents_factory.modules.policies.models import ActionRequirement, RiskLevel


class ActionRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

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
        await self._scope()
        statement = text(
            "INSERT INTO public.actions "
            "(id, tenant_id, conversation_id, customer_ref, capability, "
            "action_type, risk, required_identity_level, achieved_identity_level, "
            "parameters, parameter_digest, confirmation_required, "
            "confirmation_expires_at, approval_required, approval_route_ref, "
            "connector_binding_id, connector_name, state, created_at, updated_at) "
            "VALUES (:id, :tenant_id, :conversation_id, :customer_ref, "
            ":capability, :action_type, :risk, :required_identity, "
            ":achieved_identity, :parameters, :parameter_digest, "
            ":confirmation_required, :confirmation_expires_at, "
            ":approval_required, :approval_route_ref, :binding_id, "
            ":connector_name, 'REQUESTED', :created_at, :created_at) "
            "ON CONFLICT (id) DO NOTHING RETURNING " + _ACTION_COLUMNS
        ).bindparams(bindparam("parameters", type_=JSONB))
        result = await self._session.execute(
            statement,
            {
                "id": action_id,
                "tenant_id": self._context.tenant_id,
                "conversation_id": conversation_id,
                "customer_ref": customer_ref,
                "capability": capability,
                "action_type": action_type,
                "risk": risk,
                "required_identity": int(requirement.identity_level),
                "achieved_identity": int(achieved_identity_level),
                "parameters": parameters.value,
                "parameter_digest": parameters.digest,
                "confirmation_required": requirement.confirmation_required,
                "confirmation_expires_at": confirmation_expires_at,
                "approval_required": requirement.approval_required,
                "approval_route_ref": approval_route_ref,
                "binding_id": connector_binding_id,
                "connector_name": connector_name,
                "created_at": created_at,
            },
        )
        row = result.mappings().one_or_none()
        if row is not None:
            created = ActionRecord.from_mapping(row)
            await self._append_event(
                action=created,
                from_state=None,
                to_state="REQUESTED",
                event_type="action.requested",
                payload={},
                created_at=created_at,
            )
            return created, True
        existing = await self.get(action_id)
        if existing is None:
            raise RuntimeError("action conflict is not tenant-visible")
        return existing, False

    async def get(self, action_id: UUID, *, lock: bool = False) -> ActionRecord | None:
        await self._scope()
        suffix = " FOR UPDATE" if lock else ""
        result = await self._session.execute(
            text(
                "SELECT "
                + _ACTION_COLUMNS
                + " FROM public.actions WHERE tenant_id = :tenant_id "
                "AND id = :action_id" + suffix
            ),
            {"tenant_id": self._context.tenant_id, "action_id": action_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else ActionRecord.from_mapping(row)

    async def transition(
        self,
        *,
        action: ActionRecord,
        target: ActionState,
        event_type: str,
        payload: dict[str, object],
        changed_at: datetime,
    ) -> ActionRecord:
        await self._scope()
        result = await self._session.execute(
            text(
                "UPDATE public.actions SET state = :target, updated_at = :changed_at "
                "WHERE tenant_id = :tenant_id AND id = :action_id "
                "AND state = :expected RETURNING " + _ACTION_COLUMNS
            ),
            {
                "target": target,
                "changed_at": changed_at,
                "tenant_id": self._context.tenant_id,
                "action_id": action.id,
                "expected": action.state,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise RuntimeError("concurrent action transition")
        updated = ActionRecord.from_mapping(row)
        await self._append_event(
            action=updated,
            from_state=action.state,
            to_state=target,
            event_type=event_type,
            payload=payload,
            created_at=changed_at,
        )
        return updated

    async def confirm(
        self,
        *,
        action: ActionRecord,
        confirmation_digest: str,
        confirmed_at: datetime,
    ) -> ActionRecord:
        result = await self._session.execute(
            text(
                "UPDATE public.actions SET state = 'CONFIRMED', "
                "confirmation_digest = :confirmation_digest, "
                "confirmed_at = :confirmed_at, updated_at = :confirmed_at "
                "WHERE tenant_id = :tenant_id AND id = :action_id "
                "AND state = 'AWAITING_CONFIRMATION' RETURNING " + _ACTION_COLUMNS
            ),
            {
                "confirmation_digest": confirmation_digest,
                "confirmed_at": confirmed_at,
                "tenant_id": self._context.tenant_id,
                "action_id": action.id,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise RuntimeError("concurrent action confirmation")
        updated = ActionRecord.from_mapping(row)
        await self._append_event(
            action=updated,
            from_state=action.state,
            to_state="CONFIRMED",
            event_type="action.confirmed",
            payload={"parameter_digest": action.parameter_digest},
            created_at=confirmed_at,
        )
        return updated

    async def approve(
        self,
        *,
        action: ActionRecord,
        approval_reference: str,
        approved_at: datetime,
    ) -> ActionRecord:
        result = await self._session.execute(
            text(
                "UPDATE public.actions SET approval_reference = :approval_reference, "
                "approved_at = :approved_at, updated_at = :approved_at "
                "WHERE tenant_id = :tenant_id AND id = :action_id "
                "AND state = 'AWAITING_APPROVAL' AND approval_reference IS NULL "
                "RETURNING " + _ACTION_COLUMNS
            ),
            {
                "approval_reference": approval_reference,
                "approved_at": approved_at,
                "tenant_id": self._context.tenant_id,
                "action_id": action.id,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise RuntimeError("concurrent action approval")
        updated = ActionRecord.from_mapping(row)
        await self._append_event(
            action=updated,
            from_state=action.state,
            to_state=action.state,
            event_type="action.approved",
            payload={"approval_reference": approval_reference},
            created_at=approved_at,
        )
        return updated

    async def begin_execution(
        self, *, action: ActionRecord, started_at: datetime
    ) -> ActionRecord:
        result = await self._session.execute(
            text(
                "UPDATE public.actions SET state = 'EXECUTING', "
                "execution_attempts = execution_attempts + 1, "
                "updated_at = :started_at WHERE tenant_id = :tenant_id "
                "AND id = :action_id AND state = :expected RETURNING " + _ACTION_COLUMNS
            ),
            {
                "started_at": started_at,
                "tenant_id": self._context.tenant_id,
                "action_id": action.id,
                "expected": action.state,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise RuntimeError("concurrent action execution")
        updated = ActionRecord.from_mapping(row)
        await self._append_event(
            action=updated,
            from_state=action.state,
            to_state="EXECUTING",
            event_type="action.executing",
            payload={},
            created_at=started_at,
        )
        return updated

    async def finish(
        self,
        *,
        action: ActionRecord,
        target: ActionState,
        result_payload: dict[str, object],
        finished_at: datetime,
    ) -> ActionRecord:
        statement = text(
            "UPDATE public.actions SET state = :target, result = :result, "
            "updated_at = :finished_at WHERE tenant_id = :tenant_id "
            "AND id = :action_id AND state = :expected RETURNING " + _ACTION_COLUMNS
        ).bindparams(bindparam("result", type_=JSONB))
        result = await self._session.execute(
            statement,
            {
                "target": target,
                "result": result_payload,
                "finished_at": finished_at,
                "tenant_id": self._context.tenant_id,
                "action_id": action.id,
                "expected": action.state,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise RuntimeError("concurrent action outcome")
        updated = ActionRecord.from_mapping(row)
        await self._append_event(
            action=updated,
            from_state=action.state,
            to_state=target,
            event_type=f"action.{target.lower()}",
            payload=result_payload,
            created_at=finished_at,
        )
        return updated

    async def _append_event(
        self,
        *,
        action: ActionRecord,
        from_state: ActionState | None,
        to_state: ActionState,
        event_type: str,
        payload: dict[str, object],
        created_at: datetime,
    ) -> None:
        statement = text(
            "INSERT INTO public.action_events "
            "(id, tenant_id, action_id, version, from_state, to_state, "
            "event_type, payload, created_at) SELECT :id, :tenant_id, "
            ":action_id, coalesce(max(version), 0) + 1, :from_state, "
            ":to_state, :event_type, :payload, :created_at "
            "FROM public.action_events WHERE tenant_id = :tenant_id "
            "AND action_id = :action_id"
        ).bindparams(bindparam("payload", type_=JSONB))
        await self._session.execute(
            statement,
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "action_id": action.id,
                "from_state": from_state,
                "to_state": to_state,
                "event_type": event_type,
                "payload": payload,
                "created_at": created_at,
            },
        )

    async def _scope(self) -> None:
        await set_tenant_context(self._session, self._context.tenant_id)


_ACTION_COLUMNS = (
    "id, tenant_id, conversation_id, customer_ref, capability, action_type, "
    "risk, required_identity_level, achieved_identity_level, parameters, "
    "parameter_digest, confirmation_required, confirmation_digest, confirmed_at, "
    "confirmation_expires_at, approval_required, approval_route_ref, "
    "approval_reference, approved_at, connector_binding_id, connector_name, "
    "state, result, execution_attempts, created_at, updated_at"
)
