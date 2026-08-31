from datetime import datetime, time
from enum import StrEnum
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents_factory.common.errors import DomainError


class HandoffError(DomainError):
    def __init__(self, code: str = "handoff_unavailable", status: int = 409) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/handoff",
            title="Human handoff unavailable",
            status=status,
            detail="The requested human-control operation is unavailable.",
            code=code,
        )


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HumanResponseSurface(StrEnum):
    WHATSAPP_COEXISTENCE = "WHATSAPP_COEXISTENCE"
    EXTERNAL_INBOX = "EXTERNAL_INBOX"


class SurfaceBinding(Model):
    surface: HumanResponseSurface
    adapter: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    binding_id: str = Field(min_length=1, max_length=200)


class SupportWindow(Model):
    weekday: int = Field(ge=0, le=6)
    start: time
    end: time

    @model_validator(mode="after")
    def valid_interval(self) -> "SupportWindow":
        if self.start.tzinfo or self.end.tzinfo or self.start >= self.end:
            raise ValueError("use local same-day intervals; split overnight hours")
        return self


class HandoffConfiguration(Model):
    enabled: bool = False
    surface: SurfaceBinding | None = None
    inactivity_hours: int = Field(default=12, ge=1, le=168)
    timezone: str = "UTC"
    support_hours: tuple[SupportWindow, ...] | None = None

    @model_validator(mode="after")
    def valid_configuration(self) -> "HandoffConfiguration":
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("an IANA timezone is required") from None
        if self.enabled and self.surface is None:
            raise ValueError("enabled handoff requires a response surface")
        if self.support_hours is not None and len(self.support_hours) > 28:
            raise ValueError("too many support intervals")
        return self


class HandoffReason(StrEnum):
    EXPLICIT_REQUEST = "EXPLICIT_REQUEST"
    MANDATORY_ESCALATION = "MANDATORY_ESCALATION"
    REPEATED_INTEGRATION_FAILURE = "REPEATED_INTEGRATION_FAILURE"
    CONSEQUENTIAL_ACTION_UNRESOLVED = "CONSEQUENTIAL_ACTION_UNRESOLVED"


class HandoffRecord(Model):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    status: Literal["REQUESTED", "ACTIVE", "CLOSED"]
    reason: HandoffReason
    configuration: HandoffConfiguration
    notice_message_id: UUID
    requested_at: datetime
    last_activity_at: datetime
    closed_at: datetime | None
    event_sequence: int


class VerifiedHumanEvent(Model):
    """Only constructed by an authenticated, configured server-side adapter."""

    tenant_id: UUID
    whatsapp_account_id: UUID
    conversation_id: UUID
    handoff_id: UUID
    binding: SurfaceBinding
    event_id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=0)
    kind: Literal["ACTIVATE", "ACTIVITY", "END"]
    occurred_at: datetime

    @model_validator(mode="after")
    def aware_timestamp(self) -> "VerifiedHumanEvent":
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must include timezone")
        return self
