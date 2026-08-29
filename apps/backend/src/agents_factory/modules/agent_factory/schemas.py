from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agents_factory.modules.agent_factory.models import (
    AgentInstance,
    AgentSpecConfiguration,
    AgentSpecVersion,
    Sha256Digest,
)


class CreateAgentInstanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration: AgentSpecConfiguration


class CreateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    based_on_version_id: UUID
    configuration: AgentSpecConfiguration


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_version_id: UUID
    code_digest: Sha256Digest


class CreateAgentInstanceResponse(BaseModel):
    instance: AgentInstance
    draft: AgentSpecVersion
