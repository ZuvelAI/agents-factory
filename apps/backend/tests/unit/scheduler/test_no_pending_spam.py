from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from agents_factory.modules.observability.retention import RetentionPolicy
from scheduler.lifecycle_scan import reminder_instant


def test_reminder_is_elapsed_time_across_daylight_saving_boundaries():
    for start in (
        datetime(2026, 3, 8, 3, 30, tzinfo=ZoneInfo("America/New_York")),
        datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=ZoneInfo("America/New_York")),
    ):
        reminder = reminder_instant(start, 120)
        assert start.astimezone(UTC) - reminder == timedelta(hours=2)


def test_approved_retention_defaults_are_days_and_calendar_months():
    assert RetentionPolicy().model_dump() == {
        "conversation_days": 90,
        "trace_days": 30,
        "action_months": 12,
    }
