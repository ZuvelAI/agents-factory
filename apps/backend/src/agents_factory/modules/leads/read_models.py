"""Credential-free bounded administrative prospect views."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from .models import LeadEvidence


class ProspectSummary(BaseModel):
    id: UUID
    tenant_id: UUID
    contact_name: str | None
    contact_username: str | None
    phone_number: str | None
    declared_company: str | None
    service_interests: list[str]
    need_summary: str | None
    status: Literal["NEW"]
    capture_suppressed: bool
    identity_conflict: bool
    first_conversation_id: UUID
    last_conversation_id: UUID
    created_at: datetime
    updated_at: datetime


class ProspectPage(BaseModel):
    items: list[ProspectSummary] = Field(max_length=20)
    next_cursor: str | None = None


class ProspectEvent(BaseModel):
    id: UUID
    conversation_id: UUID
    inbound_message_id: UUID
    agent_instance_id: UUID
    agent_version_id: UUID
    agent_name: str | None = None
    version_number: int
    operation: Literal["CAPTURE", "SUPPRESS", "CONFLICT"]
    evidence: list[LeadEvidence] = Field(max_length=5)
    created_at: datetime


class ProspectEventPage(BaseModel):
    items: list[ProspectEvent] = Field(max_length=20)
    next_cursor: str | None = None


class ProspectDetail(BaseModel):
    prospect: ProspectSummary
    events: ProspectEventPage
