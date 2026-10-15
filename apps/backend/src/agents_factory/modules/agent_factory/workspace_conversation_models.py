"""Public read contracts for operational conversation logs; never raw provider data."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class ConversationSummary(BaseModel):
    id: UUID
    account_id: UUID
    customer_wa_id: str
    control_state: str
    updated_at: datetime
    last_activity_at: datetime
    agent_ids: list[UUID]


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    next_cursor: str | None = None


class OperationalMessage(BaseModel):
    id: UUID
    arrival_sequence: int
    direction: str
    message_type: str
    text: str | None
    created_at: datetime
    agent_id: UUID | None
    agent_spec_id: UUID | None
    delivery_status: str | None


class MessagePage(BaseModel):
    items: list[OperationalMessage]
    next_cursor: str | None = None
