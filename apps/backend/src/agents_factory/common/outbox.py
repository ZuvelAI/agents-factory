from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context


OutboxStatus = Literal[
    "pending",
    "processing",
    "succeeded",
    "failed",
    "dead_letter",
]


@dataclass(frozen=True, slots=True)
class OutboxJob:
    id: UUID
    tenant_id: UUID
    idempotency_key: str
    topic: str
    payload: dict[str, object]
    status: OutboxStatus
    available_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls(
            id=cast(UUID, row["id"]),
            tenant_id=cast(UUID, row["tenant_id"]),
            idempotency_key=cast(str, row["idempotency_key"]),
            topic=cast(str, row["topic"]),
            payload=cast(dict[str, object], row["payload"]),
            status=cast(OutboxStatus, row["status"]),
            available_at=cast(datetime, row["available_at"]),
            created_at=cast(datetime, row["created_at"]),
            updated_at=cast(datetime, row["updated_at"]),
        )


class OutboxService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        context: TenantContext,
        idempotency_key: str,
        topic: str,
        payload: Mapping[str, object],
        available_at: datetime | None = None,
    ) -> OutboxJob:
        await set_tenant_context(self._session, context.tenant_id)
        job_id = new_uuid7()
        statement = text(
            "INSERT INTO public.outbox_jobs "
            "(id, tenant_id, idempotency_key, topic, payload, status, "
            "available_at) "
            "VALUES (:id, :tenant_id, :idempotency_key, :topic, :payload, "
            "'pending', :available_at) "
            "ON CONFLICT (tenant_id, idempotency_key) DO UPDATE "
            "SET idempotency_key = outbox_jobs.idempotency_key "
            "RETURNING id, tenant_id, idempotency_key, topic, payload, "
            "status, available_at, created_at, updated_at"
        ).bindparams(bindparam("payload", type_=JSONB))
        result = await self._session.execute(
            statement,
            {
                "id": job_id,
                "tenant_id": context.tenant_id,
                "idempotency_key": idempotency_key,
                "topic": topic,
                "payload": dict(payload),
                "available_at": available_at or datetime.now(UTC),
            },
        )
        return OutboxJob.from_mapping(result.mappings().one())
