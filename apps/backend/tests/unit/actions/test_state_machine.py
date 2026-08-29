from __future__ import annotations

import pytest

from agents_factory.modules.actions.models import ActionState
from agents_factory.modules.actions.state_machine import (
    ActionStateMachine,
    InvalidActionTransition,
)


def test_canonical_and_optional_paths_are_explicit() -> None:
    machine = ActionStateMachine()
    state: ActionState = "REQUESTED"
    for target in (
        "IDENTITY_VERIFIED",
        "AWAITING_CONFIRMATION",
        "CONFIRMED",
        "AWAITING_APPROVAL",
        "EXECUTING",
        "SUCCEEDED",
    ):
        state = machine.transition(state, target)
    assert state == "SUCCEEDED"
    assert machine.is_terminal(state)


@pytest.mark.parametrize(
    "terminal", ("SUCCEEDED", "REJECTED", "FAILED", "UNCERTAIN", "EXPIRED")
)
def test_terminal_states_cannot_be_advanced(terminal: str) -> None:
    with pytest.raises(InvalidActionTransition):
        ActionStateMachine().transition(terminal, "EXECUTING")  # type: ignore[arg-type]


def test_low_risk_path_may_skip_confirmation_and_approval() -> None:
    machine = ActionStateMachine()
    assert machine.transition("IDENTITY_VERIFIED", "CONFIRMED") == "CONFIRMED"
    assert machine.transition("CONFIRMED", "EXECUTING") == "EXECUTING"
