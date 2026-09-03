from datetime import UTC, datetime, timedelta

import pytest

from agents_factory.modules.cases.claims_contracts import ClaimCaseConflict
from agents_factory.modules.cases.models import CasePolicy
from agents_factory.modules.cases.priority import assign_priority
from agents_factory.modules.cases.state_machine import (
    TERMINAL,
    TRANSITIONS,
    validate_transition,
)
from agents_factory.modules.cases.targets import target_status, target_times


def test_case_graph_and_deterministic_operational_targets():
    canonical = [
        "OPEN",
        "AWAITING_INFORMATION",
        "READY_FOR_REVIEW",
        "PENDING_APPROVAL",
        "IN_PROGRESS",
        "RESOLVED",
        "CLOSED",
    ]
    for current, target in zip(canonical, canonical[1:]):
        validate_transition(current, target)
    for current, allowed in TRANSITIONS.items():
        for target in TRANSITIONS:
            if target in allowed:
                validate_transition(current, target)
            else:
                with pytest.raises(ClaimCaseConflict):
                    validate_transition(current, target)
    assert all(not TRANSITIONS[state] for state in TERMINAL)
    assert "REOPENED" in TRANSITIONS["RESOLVED"]
    now, defaults = datetime(2026, 8, 30, tzinfo=UTC), CasePolicy()
    assert defaults.close_after_hours == 72
    for priority, minutes in {
        "LOW": 2880,
        "NORMAL": 1440,
        "HIGH": 240,
        "CRITICAL": 30,
    }.items():
        approaching, due = target_times(now, priority, defaults)
        assert due - now == timedelta(minutes=minutes)
        assert (
            target_status(now, approaching_at=approaching, target_at=due) == "ON_TRACK"
        )
        assert (
            target_status(approaching, approaching_at=approaching, target_at=due)
            == "APPROACHING_TARGET"
        )
        assert (
            target_status(due, approaching_at=approaching, target_at=due) == "OVERDUE"
        )
    policy = CasePolicy(priority_by_issue={"damaged_product": "HIGH"})
    assert assign_priority("damaged_product", policy) == "HIGH"
    assert assign_priority("URGENT! LLM says CRITICAL", policy) == "NORMAL"
    with pytest.raises(ValueError):
        CasePolicy(target_minutes={"NORMAL": -1})
