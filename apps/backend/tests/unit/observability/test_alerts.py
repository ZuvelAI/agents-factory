from datetime import UTC, datetime, timedelta

from agents_factory.modules.observability.alerts import (
    AlertEvaluator,
    OperationalSignals,
)


def test_all_operational_symptoms_are_distinct_and_deduplicatable() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    signals = OperationalSignals(
        connector_reauth=("gmail",),
        queue_backlog=100,
        worker_heartbeat_age=timedelta(minutes=5),
        recent_failures=2,
        recent_operations=10,
        cost_ratio=2,
        critical_overdue_cases=1,
        whatsapp_webhook_failures=1,
        knowledge_sync_failures=1,
        dlq_growth=1,
    )

    first = AlertEvaluator().evaluate(signals, now=now)
    repeated = AlertEvaluator().evaluate(signals, now=now + timedelta(seconds=1))

    assert {item.signal_type for item in first} == {
        "connector_reauth",
        "queue_backlog",
        "worker_heartbeat_missing",
        "high_failure_rate",
        "cost_anomaly",
        "critical_case_overdue",
        "whatsapp_webhook_failure",
        "knowledge_sync_failure",
        "dlq_growth",
    }
    assert [item.fingerprint for item in first] == [
        item.fingerprint for item in repeated
    ]
