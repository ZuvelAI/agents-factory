"""Per-agent publication contracts; not editable runtime snapshots."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
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
