"""Strict editing contracts; these are not executable AgentSpec snapshots."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agents_factory.modules.tenants.onboarding import (
    AgentConfiguration,
    ApprovalRoutesConfiguration,
    CapabilitiesConfiguration,
    CompanyConfiguration,
    HumanOperationsConfiguration,
    IntegrationsConfiguration,
    KnowledgeConfiguration,
    PoliciesIdentityConfiguration,
)


class ConfigurationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentEditableConfiguration(ConfigurationModel):
    schema_version: Literal[1] = 1
    purpose: str = Field(default="", max_length=2000)
    agent: AgentConfiguration = Field(default_factory=AgentConfiguration)
    knowledge: KnowledgeConfiguration = Field(default_factory=KnowledgeConfiguration)
    policies_identity: PoliciesIdentityConfiguration = Field(
        default_factory=PoliciesIdentityConfiguration
    )
    human_operations: HumanOperationsConfiguration = Field(
        default_factory=HumanOperationsConfiguration
    )
    approval_routes: ApprovalRoutesConfiguration = Field(
        default_factory=ApprovalRoutesConfiguration
    )
    capabilities: CapabilitiesConfiguration = Field(
        default_factory=CapabilitiesConfiguration
    )
    integrations: IntegrationsConfiguration = Field(
        default_factory=IntegrationsConfiguration
    )


class ValidationIssue(ConfigurationModel):
    field: str
    code: str
    message: str


class CompanyProfileView(ConfigurationModel):
    tenant_id: UUID
    revision: int
    configuration: CompanyConfiguration
    updated_at: datetime


class DraftView(ConfigurationModel):
    tenant_id: UUID
    agent_instance_id: UUID
    revision: int
    company_revision: int
    current_company_revision: int
    company_update_available: bool
    company_snapshot: CompanyConfiguration
    configuration: AgentEditableConfiguration
    provenance: dict[str, Any]
    validation_issues: list[ValidationIssue]
    updated_at: datetime


class CreateCompanyRequest(ConfigurationModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")


class CreateAgentRequest(ConfigurationModel):
    name: str = Field(min_length=1, max_length=100)


class SaveCompanyRequest(ConfigurationModel):
    expected_revision: int = Field(ge=0)
    configuration: CompanyConfiguration


class SaveDraftRequest(ConfigurationModel):
    expected_revision: int = Field(ge=1)
    configuration: AgentEditableConfiguration


class RefreshCompanyRequest(ConfigurationModel):
    expected_revision: int = Field(ge=1)
    expected_company_revision: int = Field(ge=1)


class ImportLegacyRequest(ConfigurationModel):
    expected_legacy_revision: int = Field(ge=1)
    expected_company_revision: int = Field(ge=0)
