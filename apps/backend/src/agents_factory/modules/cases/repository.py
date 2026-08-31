from __future__ import annotations

from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.cases.claims_contracts import ClaimCaseConflict
from agents_factory.modules.cases.deduplication import lock_key
from agents_factory.modules.cases.models import CaseEvent, CaseRecord


class CaseRepository:
    """All callers establish a tenant-scoped role/transaction in CaseService."""

    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context

    async def lock(self, namespace: str, key: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": lock_key(self.context.tenant_id, namespace, key)},
        )

    async def get(
        self, case_id: UUID, customer_ref: str, *, locked: bool = False
    ) -> CaseRecord | None:
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.cases WHERE tenant_id=:tenant AND id=:id AND customer_ref=:customer"
                        + (" FOR UPDATE" if locked else "")
                    ),
                    {
                        "tenant": self.context.tenant_id,
                        "id": case_id,
                        "customer": customer_ref,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        return CaseRecord.model_validate(dict(row)) if row is not None else None

    async def equivalent(self, customer_ref: str, key: str) -> CaseRecord | None:
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.cases WHERE tenant_id=:tenant AND customer_ref=:customer AND deduplication_key=:key AND status NOT IN ('CLOSED','REJECTED','CANCELLED','EXPIRED','DUPLICATE') FOR UPDATE"
                    ),
                    {
                        "tenant": self.context.tenant_id,
                        "customer": customer_ref,
                        "key": key,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        return CaseRecord.model_validate(dict(row)) if row is not None else None

    async def save(self, case: CaseRecord, *, new: bool = False) -> None:
        values = case.model_dump()
        values["intake"] = case.intake
        values["policy"] = case.policy.model_dump(mode="json")
        # Identifiers come only from the code-owned model, never from request data.
        columns = tuple(CaseRecord.model_fields)
        if new:
            sql = f"INSERT INTO public.cases ({','.join(columns)}) VALUES ({','.join(':' + key for key in columns)})"
        else:
            sql = (
                "UPDATE public.cases SET "
                + ",".join(
                    f"{key}=:{key}" for key in columns if key not in {"id", "tenant_id"}
                )
                + " WHERE tenant_id=:tenant_id AND id=:id"
            )
        await self.session.execute(
            text(sql).bindparams(
                bindparam("intake", type_=JSONB), bindparam("policy", type_=JSONB)
            ),
            values,
        )

    async def replay(
        self, operation_id: UUID, digest: str, customer_ref: str
    ) -> CaseRecord | None:
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT parameter_digest, customer_ref, receipt FROM public.case_operations WHERE tenant_id=:tenant AND id=:id"
                    ),
                    {"tenant": self.context.tenant_id, "id": operation_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if (row["parameter_digest"], row["customer_ref"]) != (digest, customer_ref):
            raise ClaimCaseConflict("case_idempotency_conflict")
        return CaseRecord.model_validate(row["receipt"])

    async def receipt(self, operation_id: UUID, digest: str, case: CaseRecord) -> None:
        await self.session.execute(
            text(
                "INSERT INTO public.case_operations(id,tenant_id,customer_ref,case_id,parameter_digest,receipt) VALUES (:id,:tenant,:customer,:case,:digest,:receipt)"
            ).bindparams(bindparam("receipt", type_=JSONB)),
            {
                "id": operation_id,
                "tenant": self.context.tenant_id,
                "customer": case.customer_ref,
                "case": case.id,
                "digest": digest,
                "receipt": case.model_dump(mode="json"),
            },
        )

    async def event(
        self,
        case: CaseRecord,
        *,
        event_type: str,
        reason: str,
        previous: CaseRecord | None = None,
        action_reference: UUID | None = None,
        approval_reference: str | None = None,
        evidence_ids: tuple[UUID, ...] = (),
    ) -> None:
        await self.session.execute(
            text(
                "INSERT INTO public.case_events(id,tenant_id,case_id,revision,event_type,actor_id,actor_type,correlation_id,reason,from_status,to_status,action_reference,approval_reference,evidence_ids,created_at) VALUES (:id,:tenant,:case,:revision,:event,:actor,:actor_type,:correlation,:reason,:old,:new,:action,:approval,:evidence,:at)"
            ).bindparams(bindparam("evidence", type_=JSONB)),
            {
                "id": new_uuid7(),
                "tenant": self.context.tenant_id,
                "case": case.id,
                "revision": case.revision,
                "event": event_type,
                "actor": self.context.actor_id,
                "actor_type": self.context.actor_type,
                "correlation": self.context.correlation_id,
                "reason": reason,
                "old": previous.status if previous else None,
                "new": case.status,
                "action": action_reference,
                "approval": approval_reference,
                "evidence": [str(item) for item in evidence_ids],
                "at": case.updated_at,
            },
        )

    async def history(self, case_id: UUID) -> tuple[CaseEvent, ...]:
        rows = (
            (
                await self.session.execute(
                    text(
                        "SELECT id,case_id,revision,event_type,actor_id,actor_type,correlation_id,reason,from_status,to_status,action_reference,approval_reference,evidence_ids,created_at FROM public.case_events WHERE tenant_id=:tenant AND case_id=:case ORDER BY created_at,id"
                    ),
                    {"tenant": self.context.tenant_id, "case": case_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(CaseEvent.model_validate(dict(row)) for row in rows)
