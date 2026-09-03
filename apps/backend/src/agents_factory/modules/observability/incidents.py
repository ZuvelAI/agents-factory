from __future__ import annotations

from datetime import timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.observability.models import IncidentRecord, IncidentSignal


class IncidentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, *, context: TenantContext, signal: IncidentSignal) -> UUID:
        await set_tenant_context(self._session, context.tenant_id)
        incident_id = new_uuid7()
        row = (
            await self._session.execute(
                text(
                    "INSERT INTO public.incidents (id,tenant_id,fingerprint,incident_type,"
                    "severity,status,title,correlation_id,first_detected_at,last_detected_at,"
                    "evidence_until) VALUES (:id,:tenant,:fingerprint,:kind,:severity,'OPEN',"
                    ":title,:correlation,:observed,:observed,:evidence_until) ON CONFLICT "
                    "(tenant_id,fingerprint) WHERE status IN ('OPEN','ACKNOWLEDGED') DO UPDATE "
                    "SET occurrence_count=incidents.occurrence_count+1,last_detected_at="
                    "excluded.last_detected_at,evidence_until=greatest(incidents.evidence_until,"
                    "excluded.evidence_until),updated_at=now() RETURNING id"
                ),
                {
                    "id": incident_id,
                    "tenant": context.tenant_id,
                    "fingerprint": signal.fingerprint,
                    "kind": signal.signal_type,
                    "severity": signal.severity,
                    "title": signal.title,
                    "correlation": context.correlation_id,
                    "observed": signal.observed_at,
                    "evidence_until": signal.observed_at + timedelta(days=90),
                },
            )
        ).scalar_one()
        await self._session.execute(
            text(
                "INSERT INTO public.incident_signals (id,tenant_id,incident_id,signal_type,"
                "summary,observed_at) VALUES (:id,:tenant,:incident,:kind,:summary,:observed)"
            ),
            {
                "id": new_uuid7(),
                "tenant": context.tenant_id,
                "incident": row,
                "kind": signal.signal_type,
                "summary": signal.summary,
                "observed": signal.observed_at,
            },
        )
        return cast(UUID, row)

    async def list_open(self, *, tenant_id: UUID) -> tuple[IncidentRecord, ...]:
        await set_tenant_context(self._session, tenant_id)
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id,incident_type,severity,status,title,correlation_id,"
                        "occurrence_count,first_detected_at,last_detected_at,evidence_until "
                        "FROM public.incidents WHERE tenant_id=:tenant AND status<>"
                        "'RESOLVED' ORDER BY severity DESC,last_detected_at DESC,id DESC LIMIT 100"
                    ),
                    {"tenant": tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(IncidentRecord.model_validate(dict(row)) for row in rows)
