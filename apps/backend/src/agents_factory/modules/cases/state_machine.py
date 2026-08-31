from agents_factory.modules.cases.claims_contracts import ClaimCaseConflict
from agents_factory.modules.cases.contracts import CaseStatus


TERMINAL = frozenset({"CLOSED", "REJECTED", "CANCELLED", "EXPIRED", "DUPLICATE"})
INTAKE_STATES = frozenset({"OPEN", "AWAITING_INFORMATION", "READY_FOR_REVIEW"})
TRANSITIONS: dict[CaseStatus, frozenset[str]] = {
    "OPEN": frozenset(
        {
            "AWAITING_INFORMATION",
            "READY_FOR_REVIEW",
            "CANCELLED",
            "EXPIRED",
            "DUPLICATE",
        }
    ),
    "AWAITING_INFORMATION": frozenset(
        {"READY_FOR_REVIEW", "CANCELLED", "EXPIRED", "DUPLICATE"}
    ),
    "READY_FOR_REVIEW": frozenset(
        {
            "AWAITING_INFORMATION",
            "PENDING_APPROVAL",
            "IN_PROGRESS",
            "REJECTED",
            "CANCELLED",
            "DUPLICATE",
        }
    ),
    "PENDING_APPROVAL": frozenset({"IN_PROGRESS", "REJECTED", "CANCELLED", "EXPIRED"}),
    "IN_PROGRESS": frozenset({"AWAITING_INFORMATION", "RESOLVED", "CANCELLED"}),
    "RESOLVED": frozenset({"REOPENED", "CLOSED"}),
    "REOPENED": frozenset(
        {"AWAITING_INFORMATION", "READY_FOR_REVIEW", "IN_PROGRESS", "CANCELLED"}
    ),
    "CLOSED": frozenset(),
    "REJECTED": frozenset(),
    "CANCELLED": frozenset(),
    "EXPIRED": frozenset(),
    "DUPLICATE": frozenset(),
}


def validate_transition(current: CaseStatus, target: CaseStatus) -> None:
    if target not in TRANSITIONS[current]:
        raise ClaimCaseConflict("invalid_case_transition")
