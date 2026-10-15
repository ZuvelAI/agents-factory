"""Credential-free read models for the internal operational workspace."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FeatureSummary(BaseModel):
    key: str
    label: str
    availability: Literal["available", "unavailable", "unknown"]
    enabled: bool
    reason: str | None = None


class ChannelSummary(BaseModel):
    account_id: UUID
    version_id: UUID | None = None
    display_number: str | None = None
    connection_status: Literal[
        "unknown", "connected", "disconnected", "review_required"
    ]
    checked_at: datetime | None = None


class AgentSummary(BaseModel):
    id: UUID
    tenant_id: UUID
    display_name: str
    published_name: str | None = None
    purpose: str | None = None
    published_version_id: UUID | None = None
    draft_version_id: UUID | None = None
    has_pending_changes: bool | None = None
    execution_status: Literal["unknown", "unassigned", "error", "paused", "serving"]
    status_checked_at: datetime | None = None
    channel_accounts: list[ChannelSummary] = Field(default_factory=list)


class CompanySummary(BaseModel):
    id: UUID
    name: str
    agent_count: int
    agents: list[AgentSummary]


class AgentConfigurationView(BaseModel):
    name: str
    purpose: str | None = None
    tone: str | None = None
    instructions: str | None = None
    model: str | None = None
    knowledge_summary: str | None = None
    capabilities: list[FeatureSummary] = Field(default_factory=list)
    integrations: list[FeatureSummary] = Field(default_factory=list)


class ChannelVersionView(BaseModel):
    version_id: UUID
    account_ids: list[UUID]
    configuration: AgentConfigurationView | None


class AgentOverview(BaseModel):
    summary: AgentSummary
    published: AgentConfigurationView | None
    draft: AgentConfigurationView | None
    unavailable_sections: list[str]
    channel_versions: list[ChannelVersionView] = Field(default_factory=list)


class CompanyPage(BaseModel):
    items: list[CompanySummary]
    next_cursor: str | None = None


class AgentPage(BaseModel):
    items: list[AgentSummary]
    next_cursor: str | None = None
    company_name: str | None = None


class CompanyOption(BaseModel):
    id: UUID
    name: str


class CompanyOptionPage(BaseModel):
    items: list[CompanyOption]
    next_cursor: str | None = None


class AccountPage(BaseModel):
    items: list[ChannelSummary]
    next_cursor: str | None = None
