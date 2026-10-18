from __future__ import annotations

import json

from agents_factory.modules.agent_factory.approved_knowledge import (
    ApprovedKnowledgeSnapshot,
)
from agents_factory.modules.agent_factory.models import (
    AgentSpecConfiguration,
    AgentModelConfiguration,
    ApprovedBusinessContext,
    HumanOperationsConfiguration,
    LanguagePolicy,
    PersonaConfiguration,
    VersionedDigestReference,
    VersionReference,
)
from agents_factory.modules.tenants.onboarding import OnboardingConfiguration


def projection_blockers(configuration: OnboardingConfiguration) -> list[str]:
    # Operational bindings are not inferred from checkboxes or prose.
    unsupported = []
    if configuration.capabilities.selected_capabilities:
        unsupported.append(
            "Conecta y valida las capacidades operativas antes de habilitarlas."
        )
    if (
        configuration.integrations.business_systems_required
        or configuration.integrations.required_connectors
    ):
        unsupported.append(
            "Faltan conexiones empresariales validadas para las integraciones seleccionadas."
        )
    if configuration.policies_identity.customer_identity_method not in (
        "NONE",
        "WHATSAPP_NUMBER",
    ):
        unsupported.append(
            "El método de identidad seleccionado todavía no está conectado."
        )
    if configuration.approval_routes.high_risk_actions_expected is not False:
        unsupported.append(
            "La aprobación de acciones de alto riesgo aún no está conectada."
        )
    human = configuration.human_operations
    if human.handoff_enabled is not False or human.awaiting_human_policy != "SILENT":
        unsupported.append(
            "La derivación automática y el acuse de espera todavía no están implementados. "
            "Desactiva la derivación automática y usa SILENT; los controles manuales de atención humana se conservan."
        )
    if configuration.capabilities.unsupported_requirements:
        unsupported.append("Revisa las necesidades declaradas como no soportadas.")
    return unsupported


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
        or not agent.supported_languages
    ):
        raise ValueError(
            "agent identity, greeting, instructions and languages are required"
        )
    unsupported = projection_blockers(configuration)
    if unsupported:
        raise ValueError("unsupported: " + ", ".join(unsupported))
    human = configuration.human_operations
    identity_method = configuration.policies_identity.customer_identity_method
    if identity_method is None:
        raise ValueError("customer identity method is required")
    locales = tuple(agent.supported_languages)
    presentation = {
        "company": company.model_dump(
            mode="json",
            include={
                "legal_name",
                "commercial_name",
                "country",
                "city",
                "industry",
                "timezone",
                "primary_locale",
                "business_description",
                "service_hours",
            },
        ),
        "agent": agent.model_dump(mode="json"),
        "policies": configuration.policies_identity.model_dump(mode="json"),
        "human_operations": human.model_dump(mode="json"),
        "approval_routes": configuration.approval_routes.model_dump(
            mode="json", exclude={"approver_emails", "route_notes"}
        ),
    }
    context = ApprovedBusinessContext(
        **knowledge.model_dump(exclude={"id", "tenant_id", "created_at"})
    )
    return AgentSpecConfiguration(
        model=AgentModelConfiguration(model=agent.model),
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
            name=identity_method.lower(),
            version="1",
        ),
        approval_routes=VersionReference(name="no_high_risk_actions", version="1"),
        knowledge=VersionedDigestReference(
            name="approved_manual_summary", version="1", digest=knowledge.digest
        ),
        approved_business_context=context,
        first_contact_greeting=agent.greeting,
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
