"""Pure conversion of the exact editing snapshot, including agent purpose."""

from pydantic import BaseModel, ConfigDict

from .approved_knowledge import ApprovedKnowledgeSnapshot
from .compiler import canonical_json
from .configuration_models import AgentEditableConfiguration, DraftView
from .models import AgentSpecConfiguration, VersionReference
from agents_factory.modules.leads.capability import (
    LEAD_CAPTURE_VERSION,
    LEAD_CAPTURE_TOOLS,
)
from .onboarding_projection import project_onboarding
from agents_factory.modules.tenants.onboarding import (
    CompanyConfiguration,
    OnboardingConfiguration,
)


class ConfigurationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    company: CompanyConfiguration
    configuration: AgentEditableConfiguration


def configuration_digest(draft: DraftView) -> str:
    return canonical_json(
        ConfigurationSnapshot(
            company=draft.company_snapshot, configuration=draft.configuration
        )
    ).digest


def project_configuration(
    draft: DraftView, knowledge: ApprovedKnowledgeSnapshot, code_digest: str
) -> AgentSpecConfiguration:
    combined = OnboardingConfiguration.model_validate(
        {
            "company": draft.company_snapshot.model_dump(mode="json"),
            **draft.configuration.model_dump(
                mode="json", exclude={"schema_version", "purpose", "lead_capture"}
            ),
        }
    )
    # Purpose is a first-class editor field, not a label to silently discard.
    if draft.configuration.purpose:
        combined.agent.instructions = f"Propósito del agente: {draft.configuration.purpose}\n{combined.agent.instructions}"
    projected = project_onboarding(combined, knowledge, code_digest)
    if draft.configuration.lead_capture and draft.configuration.lead_capture.enabled:
        return projected.model_copy(
            update={
                "agent_display_name": draft.configuration.agent.agent_name or None,
                "capabilities": (
                    *projected.capabilities,
                    VersionReference(name="lead_capture", version=LEAD_CAPTURE_VERSION),
                ),
                "permitted_tools": (
                    *projected.permitted_tools,
                    *sorted(LEAD_CAPTURE_TOOLS),
                ),
            }
        )
    return projected
