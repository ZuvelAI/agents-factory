from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.observability.models import (
    EventLinks,
    ObservabilityEvent,
    Severity,
    TraceReconstruction,
)


_SENSITIVE_FRAGMENTS = (
    "authorization",
    "body",
    "card",
    "cookie",
    "credential",
    "customer_content",
    "cvv",
    "email",
    "full_response",
    "otp",
    "password",
    "phone",
    "raw",
    "response_body",
    "secret",
    "token",
)
_MAX_PAYLOAD_BYTES = 16_000
_SENSITIVE_VALUE = re.compile(
    r"(?ix)(?:"
    r"bearer\s+[a-z0-9._~-]{12,}|"
    r"sk-(?:proj-)?[a-z0-9_-]{12,}|"
    r"eyj[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}|"
    r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+|"
    r"(?:\d[ -]?){13,19}|"
    r"\+\d(?:[ -]?\d){7,14}|"
    r"\b(?:otp|password|secret|token|cvv)\s*[:=]\s*\S+"
    r")"
)


def sanitize_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Return bounded operational metadata with sensitive fields removed."""

    sanitized = _sanitize_mapping(payload)
    encoded = json.dumps(sanitized, separators=(",", ":"), default=str).encode()
    if len(encoded) <= _MAX_PAYLOAD_BYTES:
        return sanitized
    return {
        "payload_truncated": True,
        "original_size_bytes": len(encoded),
        "retained_keys": sorted(sanitized)[:100],
    }


def _sanitize_mapping(payload: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in payload.items():
        canonical = key.lower().replace("-", "_")
        if any(fragment in canonical for fragment in _SENSITIVE_FRAGMENTS):
            continue
        if isinstance(value, Mapping):
            result[key] = _sanitize_mapping(cast(Mapping[str, object], value))
        elif isinstance(value, (list, tuple)):
            result[key] = [
                _sanitize_mapping(cast(Mapping[str, object], item))
                if isinstance(item, Mapping)
                else _sanitize_scalar(item)
                for item in value[:100]
            ]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = _sanitize_scalar(value)
        else:
            result[key] = str(value)
    return result


def _sanitize_scalar(value: object) -> object:
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        return "[REDACTED]"
    return value


class TraceRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        context: TenantContext,
        event_kind: str,
        severity: Severity,
        name: str,
        links: EventLinks = EventLinks(),
        payload: Mapping[str, object] | None = None,
        duration_ms: int | None = None,
        status: str | None = None,
        metric_value: float | None = None,
        metric_unit: str | None = None,
        occurred_at: datetime | None = None,
    ) -> UUID:
        await set_tenant_context(self._session, context.tenant_id)
        event_id = new_uuid7()
        columns = links.model_dump()
        statement = text(
            "INSERT INTO public.observability_events "
            "(id,tenant_id,event_kind,severity,name,trace_id,correlation_id,"
            "conversation_id,message_id,agent_spec_id,knowledge_version_id,capability,"
            "tool_name,connector_name,action_id,approval_id,incident_id,error_code,"
            "cost_record_id,duration_ms,metric_value,metric_unit,status,payload,occurred_at) "
            "VALUES (:id,:tenant_id,:event_kind,:severity,:name,:trace_id,:correlation_id,"
            ":conversation_id,:message_id,:agent_spec_id,:knowledge_version_id,:capability,"
            ":tool_name,:connector_name,:action_id,:approval_id,:incident_id,:error_code,"
            ":cost_record_id,:duration_ms,:metric_value,:metric_unit,:status,:payload,"
            ":occurred_at)"
        ).bindparams(bindparam("payload", type_=JSONB))
        await self._session.execute(
            statement,
            {
                "id": event_id,
                "tenant_id": context.tenant_id,
                "event_kind": event_kind,
                "severity": severity,
                "name": name,
                "correlation_id": context.correlation_id,
                "duration_ms": duration_ms,
                "metric_value": metric_value,
                "metric_unit": metric_unit,
                "status": status,
                "payload": sanitize_payload(payload or {}),
                "occurred_at": occurred_at or datetime.now(UTC),
                **columns,
            },
        )
        return event_id


class TraceReconstructor:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reconstruct(
        self, *, tenant_id: UUID, correlation_id: UUID
    ) -> TraceReconstruction:
        await set_tenant_context(self._session, tenant_id)
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM public.observability_events WHERE "
                        "tenant_id=:tenant AND correlation_id=:correlation "
                        "ORDER BY occurred_at,id"
                    ),
                    {"tenant": tenant_id, "correlation": correlation_id},
                )
            )
            .mappings()
            .all()
        )
        audits = tuple(
            cast(
                list[UUID],
                (
                    await self._session.scalars(
                        text(
                            "SELECT id FROM public.audit_events WHERE tenant_id=:tenant "
                            "AND correlation_id=:correlation ORDER BY occurred_at,id"
                        ),
                        {"tenant": tenant_id, "correlation": correlation_id},
                    )
                ).all(),
            )
        )
        events = tuple(_event(dict(row)) for row in rows)
        trace_id = next(
            (event.links.trace_id for event in events if event.links.trace_id), None
        )
        return TraceReconstruction(
            correlation_id=correlation_id,
            trace_id=trace_id,
            events=events,
            audit_event_ids=audits,
        )


def _event(row: dict[str, object]) -> ObservabilityEvent:
    links = EventLinks.model_validate(
        {key: row.pop(key, None) for key in EventLinks.model_fields}
    )
    row.pop("created_at", None)
    return ObservabilityEvent.model_validate({**row, "links": links})
