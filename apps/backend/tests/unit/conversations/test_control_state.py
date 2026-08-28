from __future__ import annotations

import pytest

from agents_factory.modules.conversations.models import (
    AwaitingHumanPolicy,
    ConversationControlState,
)
from agents_factory.modules.conversations.state_machine import (
    ConversationStateMachine,
    InvalidConversationTransition,
)


@pytest.mark.parametrize(
    ("state", "waiting_policy", "expected"),
    [
        (ConversationControlState.AI_ACTIVE, AwaitingHumanPolicy.SILENT, True),
        (
            ConversationControlState.AWAITING_HUMAN,
            AwaitingHumanPolicy.AI_CONTINUES,
            True,
        ),
        (
            ConversationControlState.AWAITING_HUMAN,
            AwaitingHumanPolicy.SILENT,
            False,
        ),
        (ConversationControlState.HUMAN_ACTIVE, AwaitingHumanPolicy.SILENT, False),
        (ConversationControlState.CLOSED, AwaitingHumanPolicy.AI_CONTINUES, False),
    ],
)
def test_response_authority_is_explicit(
    state: ConversationControlState,
    waiting_policy: AwaitingHumanPolicy,
    expected: bool,
) -> None:
    assert (
        ConversationStateMachine.may_ai_respond(
            state=state,
            awaiting_human_policy=waiting_policy,
        )
        is expected
    )


def test_only_explicit_control_commands_change_state() -> None:
    machine = ConversationStateMachine()

    assert machine.request_handoff(ConversationControlState.AI_ACTIVE) == (
        ConversationControlState.AWAITING_HUMAN
    )
    assert machine.activate_human(ConversationControlState.AWAITING_HUMAN) == (
        ConversationControlState.HUMAN_ACTIVE
    )
    assert machine.close_conversation(ConversationControlState.HUMAN_ACTIVE) == (
        ConversationControlState.CLOSED
    )
    assert (
        machine.reopen_for_inbound(
            ConversationControlState.CLOSED,
            enabled=True,
        )
        == ConversationControlState.AI_ACTIVE
    )
    assert (
        machine.reopen_for_inbound(
            ConversationControlState.CLOSED,
            enabled=False,
        )
        == ConversationControlState.CLOSED
    )


@pytest.mark.parametrize(
    ("command", "state"),
    [
        ("request_handoff", ConversationControlState.HUMAN_ACTIVE),
        ("activate_human", ConversationControlState.AI_ACTIVE),
        ("close_conversation", ConversationControlState.CLOSED),
        ("reopen_for_inbound", ConversationControlState.AI_ACTIVE),
    ],
)
def test_invalid_transition_is_rejected(
    command: str,
    state: ConversationControlState,
) -> None:
    machine = ConversationStateMachine()
    transition = getattr(machine, command)

    with pytest.raises(InvalidConversationTransition):
        if command == "reopen_for_inbound":
            transition(state, enabled=True)
        else:
            transition(state)


def test_workflow_state_cannot_implicitly_mutate_conversation_control() -> None:
    machine = ConversationStateMachine()

    with pytest.raises(InvalidConversationTransition):
        machine.close_conversation("PENDING_APPROVAL")  # type: ignore[arg-type]
