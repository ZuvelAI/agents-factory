"""Per-agent publication contracts; not editable runtime snapshots."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Self
from .publication_preview import PreviewMessage
from .models import AgentSpecVersion, Sha256Digest


class PublicationSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_kind: Literal["LEGACY", "AGENT_CONFIGURATION"]
    agent_instance_id: UUID
    version_id: UUID
    revision: int = Field(ge=1)
    company_revision: int | None = None
    source_digest: Sha256Digest | None = None
    code_digest: Sha256Digest


class WorkspaceCandidateView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: AgentSpecVersion
    source: PublicationSource
    created_at: datetime


class WorkspaceTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_kind: Literal["SCENARIOS", "PREVIEW"] = "SCENARIOS"
    expected_revision: int = Field(ge=1)
    request_key: UUID
    messages: list[PreviewMessage] | None = Field(
        default=None, min_length=1, max_length=20
    )

    @model_validator(mode="after")
    def valid_conversation(self) -> Self:
        if self.run_kind == "SCENARIOS":
            if self.messages is not None:
                raise ValueError("scenario inputs are fixed")
        else:
            if (
                not self.messages
                or len(self.messages) % 2 == 0
                or sum(len(m.text) for m in self.messages) > 20000
            ):
                raise ValueError("invalid preview history")
            if any(
                m.role != ("user" if i % 2 == 0 else "assistant")
                for i, m in enumerate(self.messages)
            ):
                raise ValueError("history must alternate from and end with user")
        return self
