from __future__ import annotations

from agents_factory.modules.conversations.models import (
    AwaitingHumanPolicy,
    ConversationControlState,
)


class InvalidConversationTransition(ValueError):
    pass


class ConversationStateMachine:
    @staticmethod
    def may_ai_respond(
        *,
        state: ConversationControlState,
        awaiting_human_policy: AwaitingHumanPolicy,
    ) -> bool:
        if state == ConversationControlState.AI_ACTIVE:
            return True
        return (
            state == ConversationControlState.AWAITING_HUMAN
            and awaiting_human_policy == AwaitingHumanPolicy.AI_CONTINUES
        )

    @staticmethod
    def request_handoff(
        state: ConversationControlState,
    ) -> ConversationControlState:
        if state != ConversationControlState.AI_ACTIVE:
            raise InvalidConversationTransition("handoff requires AI_ACTIVE")
        return ConversationControlState.AWAITING_HUMAN

    @staticmethod
    def activate_human(
        state: ConversationControlState,
    ) -> ConversationControlState:
        if state != ConversationControlState.AWAITING_HUMAN:
            raise InvalidConversationTransition(
                "human activation requires AWAITING_HUMAN"
            )
        return ConversationControlState.HUMAN_ACTIVE

    @staticmethod
    def close_conversation(
        state: ConversationControlState,
    ) -> ConversationControlState:
        if not isinstance(state, ConversationControlState) or state == (
            ConversationControlState.CLOSED
        ):
            raise InvalidConversationTransition("active conversation required")
        return ConversationControlState.CLOSED

    @staticmethod
    def reopen_for_inbound(
        state: ConversationControlState,
        *,
        enabled: bool,
    ) -> ConversationControlState:
        if state != ConversationControlState.CLOSED:
            raise InvalidConversationTransition("reopen requires CLOSED")
        if enabled:
            return ConversationControlState.AI_ACTIVE
        return ConversationControlState.CLOSED
