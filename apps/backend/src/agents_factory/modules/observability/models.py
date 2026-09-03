from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


EventKind = Literal["LOG", "METRIC", "TRACE", "HEALTH", "ALERT"]
Severity = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
HealthState = Literal["HEALTHY", "DEGRADED", "DOWN", "UNKNOWN"]
IncidentStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]


class ObservabilityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EventLinks(ObservabilityModel):
    trace_id: UUID | None = None
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    agent_spec_id: UUID | None = None
    knowledge_version_id: UUID | None = None
    capability: str | None = None
    tool_name: str | None = None
    connector_name: str | None = None
    action_id: UUID | None = None
    approval_id: UUID | None = None
    incident_id: UUID | None = None
    error_code: str | None = None
    cost_record_id: UUID | None = None


class ObservabilityEvent(ObservabilityModel):
    id: UUID
    tenant_id: UUID
    event_kind: EventKind
    severity: Severity
    name: str
    correlation_id: UUID
    links: EventLinks = EventLinks()
    duration_ms: int | None = Field(default=None, ge=0)
    metric_value: Decimal | None = None
    metric_unit: str | None = None
    status: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    occurred_at: datetime


class TraceEvent(ObservabilityEvent):
    event_kind: Literal["TRACE"] = "TRACE"


class MetricEvent(ObservabilityEvent):
    event_kind: Literal["METRIC"] = "METRIC"
    metric_value: Decimal
    metric_unit: str


class HealthEvent(ObservabilityEvent):
    event_kind: Literal["HEALTH"] = "HEALTH"
    status: HealthState


class StructuredLog(ObservabilityEvent):
    event_kind: Literal["LOG"] = "LOG"


class ComponentHealth(ObservabilityModel):
    component: str
    state: HealthState
    observed_at: datetime | None
    reason_code: str | None = None


class HealthSnapshot(ObservabilityModel):
    generated_at: datetime
    state: HealthState
    components: tuple[ComponentHealth, ...]


class IncidentRecord(ObservabilityModel):
    id: UUID
    incident_type: str
    severity: Literal["WARNING", "ERROR", "CRITICAL"]
    status: IncidentStatus
    title: str
    correlation_id: UUID
    occurrence_count: int = Field(ge=1)
    first_detected_at: datetime
    last_detected_at: datetime
    evidence_until: datetime


class IncidentSignal(ObservabilityModel):
    signal_type: str
    severity: Literal["WARNING", "ERROR", "CRITICAL"]
    title: str
    fingerprint: str
    summary: str
    observed_at: datetime


class TraceReconstruction(ObservabilityModel):
    correlation_id: UUID
    trace_id: UUID | None
    events: tuple[ObservabilityEvent, ...]
    audit_event_ids: tuple[UUID, ...]
