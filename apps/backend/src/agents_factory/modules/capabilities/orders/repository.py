from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.actions.models import ActionRecord
from agents_factory.modules.integrations.contracts import ConnectorResult


class OrderReceipts:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context

    async def claim_or_replay(self, action: ActionRecord) -> ConnectorResult | None:
        await set_tenant_context(self.session, self.context.tenant_id)
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT binding_id, operation, parameter_digest, status, result FROM public.order_operations WHERE tenant_id = :tenant AND id = :id"
                    ),
                    {"tenant": self.context.tenant_id, "id": action.id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is not None:
            if (row["binding_id"], row["operation"], row["parameter_digest"]) != (
                action.connector_binding_id,
                action.action_type,
                action.parameter_digest,
            ):
                return ConnectorResult(
                    operation=action.action_type,
                    status="REJECTED",
                    error_code="order_idempotency_conflict",
                )
            if row["status"] == "CLAIMED":
                return ConnectorResult(
                    operation=action.action_type,
                    status="UNCERTAIN",
                    error_code="interrupted_order_execution",
                )
            return ConnectorResult.model_validate(row["result"])
        await self.session.execute(
            text(
                "INSERT INTO public.order_operations(id, tenant_id, binding_id, operation, parameter_digest, status) VALUES (:id, :tenant, :binding, :operation, :digest, 'CLAIMED')"
            ),
            {
                "id": action.id,
                "tenant": self.context.tenant_id,
                "binding": action.connector_binding_id,
                "operation": action.action_type,
                "digest": action.parameter_digest,
            },
        )
        return None

    async def finish(self, action: ActionRecord, result: ConnectorResult) -> None:
        await set_tenant_context(self.session, self.context.tenant_id)
        await self.session.execute(
            text(
                "UPDATE public.order_operations SET status = :status, result = :result, updated_at = now() WHERE tenant_id = :tenant AND id = :id"
            ).bindparams(bindparam("result", type_=JSONB)),
            {
                "tenant": self.context.tenant_id,
                "id": action.id,
                "status": result.status,
                "result": result.model_dump(mode="json"),
            },
        )
