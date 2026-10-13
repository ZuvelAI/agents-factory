from __future__ import annotations

import json

from agents_factory.modules.agent_factory.approved_knowledge import (
    ApprovedKnowledgeSnapshot,
)
from agents_factory.modules.agent_factory.models import (
    AgentSpecConfiguration,
    ApprovedBusinessContext,
    HumanOperationsConfiguration,
    LanguagePolicy,
    PersonaConfiguration,
    VersionedDigestReference,
    VersionReference,
)
from agents_factory.modules.tenants.onboarding import OnboardingConfiguration


def project_onboarding(
    configuration: OnboardingConfiguration,
    knowledge: ApprovedKnowledgeSnapshot,
    code_digest: str,
) -> AgentSpecConfiguration:
    company, agent = configuration.company, configuration.agent
    if (
        not company.commercial_name.strip()
        or not agent.greeting.strip()
        or not agent.instructions.strip()
    ):
        raise ValueError("agent identity, greeting and instructions are required")
    # Operational bindings are not inferred from checkboxes or prose.
    unsupported = []
    if configuration.capabilities.selected_capabilities:
        unsupported.append("capability bindings")
    if (
        configuration.integrations.business_systems_required
        or configuration.integrations.required_connectors
    ):
        unsupported.append("connector bindings")
    if configuration.policies_identity.customer_identity_method not in (
        "NONE",
        "WHATSAPP_NUMBER",
    ):
        unsupported.append("customer identity method")
    if configuration.approval_routes.high_risk_actions_expected is not False:
        unsupported.append("high-risk approval workflow")
    human = configuration.human_operations
    if human.handoff_enabled is None or (
        human.handoff_enabled and human.response_surface != "WHATSAPP_COEXISTENCE"
    ):
        unsupported.append("human response surface")
    if configuration.capabilities.unsupported_requirements:
        unsupported.append("declared unsupported requirements")
    if unsupported:
        raise ValueError("unsupported: " + ", ".join(unsupported))
    locales = tuple(agent.supported_languages)
    presentation = {
        "company": company.model_dump(mode="json"),
        "agent": agent.model_dump(mode="json"),
        "policies": configuration.policies_identity.model_dump(mode="json"),
        "human_operations": human.model_dump(mode="json"),
        "approval_routes": configuration.approval_routes.model_dump(mode="json"),
    }
    context = ApprovedBusinessContext(
        **knowledge.model_dump(exclude={"id", "tenant_id", "created_at"})
    )
    return AgentSpecConfiguration(
        product_version="1.0.0",
        persona=PersonaConfiguration(
            version="panel-v1",
            business_name=company.commercial_name,
            instructions="Follow the configured greeting, tone, formality and supported languages. "
            "Use business information without inventing missing facts.\n"
            + json.dumps(presentation, ensure_ascii=False, sort_keys=True),
        ),
        policy=VersionReference(name="customer_service", version="1"),
        identity_policy=VersionReference(
            name=configuration.policies_identity.customer_identity_method.lower(),
            version="1",
        ),
        approval_routes=VersionReference(name="no_high_risk_actions", version="1"),
        knowledge=VersionedDigestReference(
            name="approved_manual_summary", version="1", digest=knowledge.digest
        ),
        approved_business_context=context,
        language=LanguagePolicy(
            supported_locales=locales,
            default_locale=company.primary_locale
            if company.primary_locale in locales
            else locales[0],
        ),
        human_operations=HumanOperationsConfiguration(
            version="1",
            handoff_enabled=bool(human.handoff_enabled),
            handoff_surface_available=False,
            awaiting_human_policy=human.awaiting_human_policy,
        ),
        code_digest=code_digest,
    )
