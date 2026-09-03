from datetime import datetime, timedelta

from agents_factory.modules.cases.models import CasePolicy, CasePriority, TargetStatus


def target_times(
    started_at: datetime, priority: CasePriority, policy: CasePolicy
) -> tuple[datetime, datetime]:
    minutes = policy.target_minutes.get(priority)
    if minutes is None or not 1 <= minutes <= 525600:
        raise ValueError("invalid_case_response_target")
    duration = timedelta(minutes=minutes)
    return started_at + duration * policy.approaching_fraction, started_at + duration


def target_status(
    now: datetime, *, approaching_at: datetime, target_at: datetime
) -> TargetStatus:
    if now >= target_at:
        return "OVERDUE"
    if now >= approaching_at:
        return "APPROACHING_TARGET"
    return "ON_TRACK"
