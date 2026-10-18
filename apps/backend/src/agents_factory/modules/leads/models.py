"""Bounded model proposals and server-owned identity contracts."""

import re
from dataclasses import dataclass
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from agents_factory.modules.runtime.contracts import TurnMessage

_CREDENTIAL = re.compile(
    r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|Bearer\s+\S{16,}|EA[A-Za-z0-9]{40,})",
    re.IGNORECASE,
)
Label = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class LeadEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message_id: UUID
    quote: str = Field(min_length=1, max_length=500)

    @field_validator("quote")
    @classmethod
    def safe_quote(cls, value: str) -> str:
        if not value.strip() or _CREDENTIAL.search(value):
            raise ValueError("unsafe evidence")
        return value


class LeadProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation: Literal["CAPTURE", "SUPPRESS"]
    evidence: tuple[LeadEvidence, ...] = Field(min_length=1, max_length=5)
    service_interest: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
        ]
        | None
    ) = None
    need_summary: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
        ]
        | None
    ) = None
    declared_name: Label | None = None
    declared_company: Label | None = None
    corrected_fields: frozenset[Literal["name", "company", "need_summary"]] = (
        frozenset()
    )

    @model_validator(mode="after")
    def safe_payload(self) -> Self:
        values = (
            self.service_interest,
            self.need_summary,
            self.declared_name,
            self.declared_company,
        )
        if self.operation == "SUPPRESS" and (any(values) or self.corrected_fields):
            raise ValueError("suppression cannot contain commercial fields")
        if any(_CREDENTIAL.search(value) for value in values if value):
            raise ValueError("unsafe commercial data")
        for key, value in (
            ("name", self.declared_name),
            ("company", self.declared_company),
            ("need_summary", self.need_summary),
        ):
            if key in self.corrected_fields and value is None:
                raise ValueError("correction requires a replacement value")
        return self


def validate_evidence(
    proposal: LeadProposal, messages: tuple[TurnMessage, ...], inbound_message_id: UUID
) -> None:
    """Validate literal customer evidence; semantics remain the agent's task."""
    by_id = {message.id: message for message in messages}
    if inbound_message_id not in {e.message_id for e in proposal.evidence}:
        raise ValueError("evidence must include current inbound")
    for evidence in proposal.evidence:
        message = by_id.get(evidence.message_id)
        if (
            message is None
            or message.role != "user"
            or evidence.quote not in message.text
        ):
            raise ValueError("evidence must quote a customer message")
    quoted = "\n".join(e.quote for e in proposal.evidence).casefold()
    if any(
        value.casefold() not in quoted
        for value in (proposal.declared_name, proposal.declared_company)
        if value
    ):
        raise ValueError("declared values must occur in evidence")


@dataclass(frozen=True, slots=True)
class TrustedLeadContext:
    tenant_id: UUID
    account_id: UUID
    customer_wa_id: str
    conversation_id: UUID
    inbound_message_id: UUID
    agent_instance_id: UUID
    agent_version_id: UUID
    phone_number: str | None
    provider_keys: tuple[str, ...]
    profile_name: str | None = None
    username: str | None = None


@dataclass(frozen=True, slots=True)
class LeadCaptureOutcome:
    status: Literal["RECORDED", "SUPPRESSED", "IDENTITY_CONFLICT", "REJECTED"]
    prospect_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class LeadSubjectResolution:
    subject_id: UUID | None
    conflicted: bool = False
    conflict_subject_ids: tuple[UUID, ...] = ()
