from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.cases.deduplication import lock_key
from agents_factory.modules.cases.service import require_backend
from agents_factory.modules.integrations.contracts import ConnectorResult
from agents_factory.modules.runtime.contracts import reject_sensitive_fields


class PersistentClaimDeliveryLedger:
    available = True

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @asynccontextmanager
    async def serialized(
        self, *, context: TenantContext, key: str
    ) -> AsyncIterator[None]:
        require_backend(context)
        if not 1 <= len(key) <= 1500:
            raise ValueError("invalid_claim_delivery_key")
        # Dedicated coordination transaction holds no application row locks.
        # Transaction advisory locks also work with transaction-mode pooling.
        async with self.sessions.begin() as guard:
            await guard.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await guard.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": lock_key(context.tenant_id, "delivery", key)},
            )
            yield

    @asynccontextmanager
    async def _transaction(self, context: TenantContext) -> AsyncIterator[AsyncSession]:
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(session, context.tenant_id)
            yield session

    async def _finish(
        self, context: TenantContext, key: str, result: ConnectorResult
    ) -> None:
        async with self._transaction(context) as session:
            await session.execute(
                text(
                    "UPDATE public.case_delivery_operations SET status=:status,result=:result,updated_at=now() WHERE tenant_id=:tenant AND effect_key=:key AND status='CLAIMED'"
                ).bindparams(bindparam("result", type_=JSONB)),
                {
                    "tenant": context.tenant_id,
                    "key": key,
                    "status": result.status,
                    "result": result.model_dump(mode="json"),
                },
            )

    async def once(
        self,
        *,
        context: TenantContext,
        key: str,
        digest: str,
        operation: str,
        effect: Callable[[], Awaitable[ConnectorResult]],
    ) -> ConnectorResult:
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("invalid_claim_delivery_digest")
        # Separate namespace prevents nesting deadlocks with destination locking;
        # once remains safe even if another internal caller omits the outer guard.
        async with self.serialized(context=context, key=f"effect:{key}"):
            async with self._transaction(context) as session:
                row = (
                    (
                        await session.execute(
                            text(
                                "SELECT parameter_digest,operation,status,result FROM public.case_delivery_operations WHERE tenant_id=:tenant AND effect_key=:key"
                            ),
                            {"tenant": context.tenant_id, "key": key},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is not None:
                    if (row["parameter_digest"], row["operation"]) != (
                        digest,
                        operation,
                    ):
                        return ConnectorResult(
                            operation=operation,
                            status="REJECTED",
                            error_code="claim_delivery_payload_conflict",
                        )
                    if row["status"] != "CLAIMED":
                        return ConnectorResult.model_validate(row["result"])
                else:
                    await session.execute(
                        text(
                            "INSERT INTO public.case_delivery_operations(id,tenant_id,effect_key,parameter_digest,operation,status) VALUES (:id,:tenant,:key,:digest,:operation,'CLAIMED')"
                        ),
                        {
                            "id": new_uuid7(),
                            "tenant": context.tenant_id,
                            "key": key,
                            "digest": digest,
                            "operation": operation,
                        },
                    )
            # Claim is committed BEFORE the side effect. Cancellation/crash leaves
            # it durable; a later invocation records UNCERTAIN without calling out.
            if row is not None:
                result = ConnectorResult(
                    operation=operation,
                    status="UNCERTAIN",
                    error_code="interrupted_claim_delivery",
                )
            else:
                try:
                    result = await effect()
                    if result.operation != operation:
                        raise ValueError("claim_delivery_operation_mismatch")
                    reject_sensitive_fields(result.data)
                except Exception:
                    result = ConnectorResult(
                        operation=operation,
                        status="UNCERTAIN",
                        error_code="claim_delivery_unconfirmed",
                    )
            await self._finish(context, key, result)
            return result
