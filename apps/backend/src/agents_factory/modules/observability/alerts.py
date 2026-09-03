from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agents_factory.modules.observability.models import IncidentSignal


@dataclass(frozen=True, slots=True)
class OperationalSignals:
    connector_reauth: tuple[str, ...] = ()
    queue_backlog: int = 0
    worker_heartbeat_age: timedelta | None = None
    recent_failures: int = 0
    recent_operations: int = 0
    cost_ratio: float = 1.0
    critical_overdue_cases: int = 0
    whatsapp_webhook_failures: int = 0
    knowledge_sync_failures: int = 0
    dlq_growth: int = 0


class AlertEvaluator:
    def evaluate(
        self, signals: OperationalSignals, *, now: datetime | None = None
    ) -> tuple[IncidentSignal, ...]:
        observed_at = now or datetime.now(UTC)
        candidates: list[tuple[str, str, str, str]] = []
        for connector in signals.connector_reauth:
            candidates.append(
                ("connector_reauth", "ERROR", f"Reconnect {connector}", connector)
            )
        if signals.queue_backlog >= 100:
            candidates.append(
                (
                    "queue_backlog",
                    "WARNING",
                    "Queue backlog",
                    str(signals.queue_backlog),
                )
            )
        if signals.worker_heartbeat_age and signals.worker_heartbeat_age >= timedelta(
            minutes=5
        ):
            candidates.append(
                (
                    "worker_heartbeat_missing",
                    "ERROR",
                    "Worker heartbeat missing",
                    str(int(signals.worker_heartbeat_age.total_seconds())),
                )
            )
        failure_rate = signals.recent_failures / max(signals.recent_operations, 1)
        if signals.recent_operations >= 10 and failure_rate >= 0.2:
            candidates.append(
                (
                    "high_failure_rate",
                    "ERROR",
                    "High operation failure rate",
                    f"{failure_rate:.3f}",
                )
            )
        if signals.cost_ratio >= 2.0:
            candidates.append(
                (
                    "cost_anomaly",
                    "WARNING",
                    "Tenant cost anomaly",
                    f"{signals.cost_ratio:.3f}",
                )
            )
        if signals.critical_overdue_cases:
            candidates.append(
                (
                    "critical_case_overdue",
                    "CRITICAL",
                    "Critical case overdue",
                    str(signals.critical_overdue_cases),
                )
            )
        if signals.whatsapp_webhook_failures:
            candidates.append(
                (
                    "whatsapp_webhook_failure",
                    "ERROR",
                    "WhatsApp webhook failure",
                    str(signals.whatsapp_webhook_failures),
                )
            )
        if signals.knowledge_sync_failures:
            candidates.append(
                (
                    "knowledge_sync_failure",
                    "ERROR",
                    "Knowledge synchronization failure",
                    str(signals.knowledge_sync_failures),
                )
            )
        if signals.dlq_growth:
            candidates.append(
                (
                    "dlq_growth",
                    "ERROR",
                    "Dead-letter queue growth",
                    str(signals.dlq_growth),
                )
            )
        return tuple(
            IncidentSignal(
                signal_type=kind,
                severity=severity,  # type: ignore[arg-type]
                title=title,
                fingerprint=hashlib.sha256(f"{kind}:{title}".encode()).hexdigest(),
                summary=f"{kind} observed value {value}",
                observed_at=observed_at,
            )
            for kind, severity, title, value in candidates
        )
