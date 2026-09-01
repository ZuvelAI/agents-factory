from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents_factory.modules.agent_factory.models import (
    AgentInstance,
    AgentSpecState,
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


class CreateCustomerServiceDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    business_name: str = Field(min_length=1, max_length=200)


class AgentPresentationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version_id: UUID
    agent_name: str | None = Field(default=None, max_length=80)
    tone: str | None = Field(default=None, min_length=1, max_length=120)
    formality: str | None = Field(default=None, min_length=1, max_length=80)
    brand_vocabulary: tuple[str, ...] | None = Field(default=None, max_length=100)
    greeting: str | None = Field(default=None, min_length=1, max_length=500)
    supported_locales: tuple[Literal["es-CO", "en-US"], ...] | None = Field(
        default=None, max_length=2
    )
    default_locale: Literal["es-CO", "en-US"] | None = None

    @model_validator(mode="after")
    def validate_locale_update(self) -> AgentPresentationUpdateRequest:
        allowed = {"es-CO", "en-US"}
        if self.supported_locales is not None:
            if not self.supported_locales or len(set(self.supported_locales)) != len(
                self.supported_locales
            ):
                raise ValueError("supported locales must be non-empty and unique")
            if not set(self.supported_locales) <= allowed:
                raise ValueError("only approved v1 locales are supported")
        if self.default_locale is not None and self.default_locale not in allowed:
            raise ValueError("only approved v1 locales are supported")
        return self


class AgentEditorVersion(BaseModel):
    id: UUID
    version_number: int
    state: AgentSpecState
    created_at: datetime


class AgentEditorState(BaseModel):
    instance: AgentInstance
    editable_version: AgentSpecVersion
    production_version: AgentEditorVersion | None
    quick_options: tuple[str, ...]
