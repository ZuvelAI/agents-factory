from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ConversationControlState(StrEnum):
    AI_ACTIVE = "AI_ACTIVE"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    CLOSED = "CLOSED"


class AwaitingHumanPolicy(StrEnum):
    AI_CONTINUES = "AI_CONTINUES"
    SILENT = "SILENT"


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    tenant_id: UUID
    whatsapp_account_id: UUID
    customer_wa_id: str
    control_state: ConversationControlState
    state_version: int
    opened_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class Message:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    source_event_id: UUID
    provider_message_id: str
    message_type: str
    content: dict[str, object]
    provider_timestamp: datetime
    arrival_sequence: int


@dataclass(frozen=True, slots=True)
class ConversationIngestResult:
    conversation_id: UUID
    message_id: UUID
    message_created: bool
    control_state: ConversationControlState
    response_queued: bool
