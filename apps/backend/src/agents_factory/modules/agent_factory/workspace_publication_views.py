"""Typed read views kept separate from command/evidence dependency graph."""

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from .channel_binding import AccountAgentBinding
from .models import AgentSpecVersion
from .publication_evidence import PublicationTestRun
from .workspace_publication_models import WorkspaceCandidateView


class PublicationAccountView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    display_phone_number: str | None
    status: str
    health_status: str
    binding: AccountAgentBinding | None


class WorkspacePublicationState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_revision: int
    company_revision: int
    blockers: list[str]
    candidates: list[WorkspaceCandidateView]
    runs: list[PublicationTestRun]
    accounts: list[PublicationAccountView]
    versions: list[AgentSpecVersion]
    bindings: list[AccountAgentBinding]
    rollback_targets: list[UUID] = Field(default_factory=list)
    next_cursor: str | None
    section: Literal["candidates", "runs", "accounts", "versions"]
