from __future__ import annotations

from agents_factory.modules.actions.models import ActionState


class InvalidActionTransition(ValueError):
    pass


_TRANSITIONS: dict[ActionState, frozenset[ActionState]] = {
    "REQUESTED": frozenset({"IDENTITY_VERIFIED", "REJECTED"}),
    "IDENTITY_VERIFIED": frozenset({"AWAITING_CONFIRMATION", "CONFIRMED"}),
    "AWAITING_CONFIRMATION": frozenset({"CONFIRMED", "REJECTED", "EXPIRED"}),
    "CONFIRMED": frozenset({"AWAITING_APPROVAL", "EXECUTING", "FAILED"}),
    "AWAITING_APPROVAL": frozenset({"EXECUTING", "REJECTED", "FAILED", "EXPIRED"}),
    "EXECUTING": frozenset({"SUCCEEDED", "FAILED", "UNCERTAIN", "HANDED_OFF"}),
    "SUCCEEDED": frozenset(),
    "REJECTED": frozenset(),
    "FAILED": frozenset(),
    "UNCERTAIN": frozenset(),
    "EXPIRED": frozenset(),
    "HANDED_OFF": frozenset(),
}


class ActionStateMachine:
    def transition(self, current: ActionState, target: ActionState) -> ActionState:
        if target not in _TRANSITIONS[current]:
            raise InvalidActionTransition(f"{current} -> {target}")
        return target

    def is_terminal(self, state: ActionState) -> bool:
        return not _TRANSITIONS[state]
