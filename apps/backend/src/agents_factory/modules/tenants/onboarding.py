from __future__ import annotations

from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.database import set_tenant_context
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY
from agents_factory.modules.tenants.repository import TenantRepository


StepKey = Literal[
    "company",
    "agent",
    "capabilities",
    "integrations",
    "knowledge",
    "policies-identity",
    "human-operations",
    "approval-routes",
    "whatsapp",
    "test",
    "quality-gate",
    "production",
]
EditableStepKey = Literal[
    "company",
    "agent",
    "capabilities",
    "integrations",
    "knowledge",
    "policies-identity",
    "human-operations",
    "approval-routes",
]
StepStatus = Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETE", "BLOCKED"]
OnboardingClassification = Literal[
    "STANDARD", "CUSTOM_CONNECTOR", "CUSTOM_WORKFLOW", "NEW_CAPABILITY"
]


class WizardModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CompanyConfiguration(WizardModel):
    legal_name: str = Field(default="", max_length=200)
    commercial_name: str = Field(default="", max_length=200)
    country: str = Field(default="", max_length=100)
    city: str = Field(default="", max_length=100)
    industry: str = Field(default="", max_length=160)
    timezone: str = Field(default="America/Bogota", max_length=100)
    primary_locale: Literal["es-CO", "en-US"] = "es-CO"
    business_description: str = Field(default="", max_length=5_000)
    service_hours: str = Field(default="", max_length=500)
    whatsapp_volume: str = Field(default="unknown", max_length=100)
    responsible_person: str = Field(default="", max_length=200)
    privacy_contact: str = Field(default="", max_length=200)
    incident_contact: str = Field(default="", max_length=200)


class AgentConfiguration(WizardModel):
    model: Literal["gpt-5.6-luna", "gpt-6-luna"] = "gpt-5.6-luna"
    agent_name: str = Field(default="", max_length=100)
    greeting_style: Literal["NAMED", "BRAND_ONLY"] = "BRAND_ONLY"
    tone: Literal["PROFESSIONAL_WARM", "PROFESSIONAL_DIRECT", "FRIENDLY"] = (
        "PROFESSIONAL_WARM"
    )
    formality: Literal["USTED", "TU"] = "USTED"
    greeting: str = Field(default="", max_length=1_000)
    instructions: str = Field(default="", max_length=50_000)
    supported_languages: list[Literal["es-CO", "en-US"]] = Field(
        default_factory=lambda: cast(list[Literal["es-CO", "en-US"]], ["es-CO"]),
        max_length=2,
    )
    brand_vocabulary: str = Field(default="", max_length=2_000)


class UnsupportedRequirement(WizardModel):
    description: str = Field(min_length=1, max_length=500)
    classification: OnboardingClassification


class CapabilitiesConfiguration(WizardModel):
    use_cases: list[str] = Field(default_factory=list, max_length=20)
    selected_capabilities: list[Literal["appointments", "orders", "returns_claims"]] = (
        Field(default_factory=list, max_length=3)
    )
    unsupported_requirements: list[UnsupportedRequirement] = Field(
        default_factory=list, max_length=20
    )
    onboarding_classification: OnboardingClassification = "STANDARD"


class IntegrationsConfiguration(WizardModel):
    business_systems_required: bool | None = None
    required_connectors: list[
        Literal["google_workspace", "google_sheets", "woocommerce"]
    ] = Field(default_factory=list, max_length=3)
    connection_notes: str = Field(default="", max_length=2_000)


class KnowledgeConfiguration(WizardModel):
    source_name: str = Field(default="", max_length=300)
    source_type: Literal["PDF", "WEBSITE", "INTERNAL_TEXT"] = "PDF"
    source_reference: str = Field(default="", max_length=2_000)
    authority: Literal["OFFICIAL", "OPERATIONAL", "REFERENCE"] = "OFFICIAL"
    approved_summary: str = Field(default="", max_length=10_000)
    critical_conflicts: int = Field(default=0, ge=0, le=10_000)
    review_confirmed: bool = False


class PoliciesIdentityConfiguration(WizardModel):
    pricing_response: Literal["QUOTE_REQUIRED", "APPROVED_PRICES_ONLY"] | None = None
    privacy_policy_status: Literal["NOT_DEFINED", "DRAFT", "APPROVED"] | None = None
    customer_identity_method: (
        Literal["NONE", "WHATSAPP_NUMBER", "ORDER_DATA", "ONE_TIME_CODE"] | None
    ) = None
    policy_notes: str = Field(default="", max_length=5_000)


class HumanOperationsConfiguration(WizardModel):
    handoff_enabled: bool | None = None
    response_surface: Literal["NONE", "WHATSAPP_COEXISTENCE", "EXTERNAL_HELPDESK"] = (
        "NONE"
    )
    support_hours: str = Field(default="", max_length=500)
    awaiting_human_policy: Literal["SILENT", "ACKNOWLEDGE"] = "SILENT"


class ApprovalRoutesConfiguration(WizardModel):
    high_risk_actions_expected: bool | None = None
    approver_emails: list[str] = Field(default_factory=list, max_length=20)
    strategy: Literal["FIRST_RESPONSE"] = "FIRST_RESPONSE"
    route_notes: str = Field(default="", max_length=2_000)


class OnboardingConfiguration(WizardModel):
    company: CompanyConfiguration = Field(default_factory=CompanyConfiguration)
    agent: AgentConfiguration = Field(default_factory=AgentConfiguration)
    capabilities: CapabilitiesConfiguration = Field(
        default_factory=CapabilitiesConfiguration
    )
    integrations: IntegrationsConfiguration = Field(
        default_factory=IntegrationsConfiguration
    )
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


class DocumentationLink(BaseModel):
    label: str
    href: str


class OnboardingStep(BaseModel):
    key: StepKey
    position: int
    title: str
    instructions: str
    status: StepStatus
    required_fields: list[str]
    test_actions: list[str]
    blockers: list[str]
    warnings: list[str]
    documentation_links: list[DocumentationLink]
    data: dict[str, object]


class OnboardingResponse(BaseModel):
    tenant_id: UUID
    tenant_name: str
    revision: int
    updated_at: datetime | None
    current_step: StepKey
    completed_steps: int
    total_steps: Literal[12] = 12
    steps: list[OnboardingStep]


class UpdateOnboardingStepRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    data: dict[str, object]


class DomainFacts(BaseModel):
    knowledge_frozen: bool = False
    test_checks_passed: bool = False
    quality_gate_passed: bool = False
    healthy_whatsapp: bool = False
    whatsapp_configured: bool = False
    latest_agent_state: (
        Literal["DRAFT", "TEST", "QUALITY_GATE", "PRODUCTION"] | None
    ) = None
    production_deployed: bool = False


class StoredOnboarding(BaseModel):
    revision: int
    configuration: OnboardingConfiguration
    updated_at: datetime


_STEP_MODELS: dict[EditableStepKey, type[WizardModel]] = {
    "company": CompanyConfiguration,
    "agent": AgentConfiguration,
    "capabilities": CapabilitiesConfiguration,
    "integrations": IntegrationsConfiguration,
    "knowledge": KnowledgeConfiguration,
    "policies-identity": PoliciesIdentityConfiguration,
    "human-operations": HumanOperationsConfiguration,
    "approval-routes": ApprovalRoutesConfiguration,
}
_ATTRIBUTE_BY_STEP: dict[EditableStepKey, str] = {
    "company": "company",
    "agent": "agent",
    "capabilities": "capabilities",
    "integrations": "integrations",
    "knowledge": "knowledge",
    "policies-identity": "policies_identity",
    "human-operations": "human_operations",
    "approval-routes": "approval_routes",
}
_DOCS = [
    DocumentationLink(
        label="Especificación maestra — onboarding",
        href="https://github.com/ZuvelAI/agents-factory/blob/main/docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md#29-canonical-client-onboarding-wizard",
    )
]


class OnboardingRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def read(self) -> StoredOnboarding | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT revision, configuration, updated_at "
                "FROM public.tenant_onboarding_configs "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": self._context.tenant_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return StoredOnboarding(
            revision=row["revision"],
            configuration=OnboardingConfiguration.model_validate(row["configuration"]),
            updated_at=row["updated_at"],
        )

    async def save(
        self,
        *,
        configuration: OnboardingConfiguration,
        expected_revision: int,
    ) -> StoredOnboarding | None:
        await self._scope()
        serialized = configuration.model_dump(mode="json")
        if expected_revision == 0:
            statement = text(
                "INSERT INTO public.tenant_onboarding_configs "
                "(tenant_id, revision, configuration) "
                "VALUES (:tenant_id, 1, :configuration) "
                "ON CONFLICT (tenant_id) DO NOTHING "
                "RETURNING revision, configuration, updated_at"
            ).bindparams(bindparam("configuration", type_=JSONB))
            parameters = {
                "tenant_id": self._context.tenant_id,
                "configuration": serialized,
            }
        else:
            statement = text(
                "UPDATE public.tenant_onboarding_configs "
                "SET configuration = :configuration, revision = revision + 1, "
                "updated_at = now() WHERE tenant_id = :tenant_id "
                "AND revision = :expected_revision "
                "RETURNING revision, configuration, updated_at"
            ).bindparams(bindparam("configuration", type_=JSONB))
            parameters = {
                "tenant_id": self._context.tenant_id,
                "configuration": serialized,
                "expected_revision": expected_revision,
            }
        result = await self._session.execute(statement, parameters)
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return StoredOnboarding(
            revision=row["revision"],
            configuration=OnboardingConfiguration.model_validate(row["configuration"]),
            updated_at=row["updated_at"],
        )

    async def domain_facts(self, *, code_digest: str | None = None) -> DomainFacts:
        await self._scope()
        from agents_factory.modules.agent_factory.approved_knowledge import (
            ApprovedKnowledgeDocument,
        )
        from agents_factory.modules.agent_factory.compiler import canonical_json

        stored = await self.read()
        digest = None
        if stored is not None:
            knowledge = stored.configuration.knowledge
            if (
                knowledge.review_confirmed
                and knowledge.critical_conflicts == 0
                and all(
                    item.strip()
                    for item in (
                        knowledge.source_name,
                        knowledge.source_reference,
                        knowledge.approved_summary,
                    )
                )
            ):
                document = ApprovedKnowledgeDocument(
                    **knowledge.model_dump(exclude={"critical_conflicts"})
                )
                digest = canonical_json(document).digest
        result = await self._session.execute(
            text(
                "SELECT "
                "exists(SELECT 1 FROM public.whatsapp_accounts "
                "WHERE tenant_id = :tenant_id AND status = 'active') "
                "AS whatsapp_configured, "
                "exists(SELECT 1 FROM public.whatsapp_accounts "
                "WHERE tenant_id = :tenant_id AND status = 'active' "
                "AND health_status = 'HEALTHY') AS healthy_whatsapp, "
                "(SELECT state FROM public.agent_spec_versions "
                "WHERE tenant_id = :tenant_id "
                "ORDER BY updated_at DESC, id DESC LIMIT 1) AS latest_agent_state, "
                "exists(SELECT 1 FROM public.agent_spec_deployments "
                "WHERE tenant_id = :tenant_id) AS production_deployed"
            ),
            {"tenant_id": self._context.tenant_id},
        )
        row = result.mappings().one()
        facts = DomainFacts.model_validate(row)
        if digest is not None:
            frozen = await self._session.scalar(
                text(
                    "SELECT exists(SELECT 1 FROM public.agent_approved_knowledge_versions "
                    "WHERE tenant_id=:tenant AND digest=:digest)"
                ),
                {"tenant": self._context.tenant_id, "digest": digest},
            )
            facts.knowledge_frozen = bool(frozen)
        if stored is not None and code_digest is not None:
            candidate = await self._session.execute(
                text(
                    "SELECT v.id,v.state,v.compiled_digest,v.configuration->'knowledge'->>'digest' AS knowledge_digest "
                    "FROM public.panel_agent_candidates c JOIN public.agent_spec_versions v ON v.tenant_id=c.tenant_id AND v.id=c.version_id "
                    "WHERE c.tenant_id=:tenant AND c.onboarding_revision=:revision AND c.code_digest=:code "
                    "ORDER BY c.created_at DESC LIMIT 1"
                ),
                {
                    "tenant": self._context.tenant_id,
                    "revision": stored.revision,
                    "code": code_digest,
                },
            )
            candidate_row = candidate.mappings().one_or_none()
            facts.latest_agent_state = (
                None if candidate_row is None else candidate_row["state"]
            )
            facts.production_deployed = False
            if candidate_row is not None:
                facts.test_checks_passed = bool(
                    await self._session.scalar(
                        text(
                            "SELECT exists(SELECT 1 FROM public.agent_publication_test_runs run JOIN public.agent_publication_test_results r "
                            "ON r.tenant_id=run.tenant_id AND r.run_id=run.id WHERE run.tenant_id=:tenant AND run.version_id=:version "
                            "AND run.code_digest=:code AND run.expires_at>now() AND r.result->>'checks_passed'='true')"
                        ),
                        {
                            "tenant": self._context.tenant_id,
                            "version": candidate_row["id"],
                            "code": code_digest,
                        },
                    )
                )
                from agents_factory.modules.agent_factory.publication_evidence import (
                    PersistedPanelQualityGate,
                )

                facts.quality_gate_passed = (
                    await PersistedPanelQualityGate(
                        self._session, self._context
                    ).evaluate(
                        agent_spec_digest=candidate_row["compiled_digest"],
                        knowledge_digest=candidate_row["knowledge_digest"],
                        code_digest=code_digest,
                    )
                ) is not None
                facts.production_deployed = bool(
                    await self._session.scalar(
                        text(
                            "SELECT exists(SELECT 1 FROM public.account_agent_bindings WHERE tenant_id=:tenant AND version_id=:version)"
                        ),
                        {
                            "tenant": self._context.tenant_id,
                            "version": candidate_row["id"],
                        },
                    )
                )
        else:
            facts.latest_agent_state = None
            facts.production_deployed = False
        return facts

    async def _scope(self) -> None:
        await set_tenant_context(self._session, self._context.tenant_id)


class OnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        code_digest: str | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._repository = OnboardingRepository(session, context)
        self._code_digest = code_digest

    async def read(self) -> OnboardingResponse:
        tenant = await TenantRepository(self._session).get(self._context.tenant_id)
        if tenant is None:
            raise _tenant_not_found()
        stored = await self._repository.read()
        config = OnboardingConfiguration() if stored is None else stored.configuration
        return _build_response(
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            revision=0 if stored is None else stored.revision,
            updated_at=None if stored is None else stored.updated_at,
            config=config,
            facts=await self._repository.domain_facts(code_digest=self._code_digest),
        )

    async def update(
        self,
        *,
        step: EditableStepKey,
        request: UpdateOnboardingStepRequest,
    ) -> OnboardingResponse:
        tenant = await TenantRepository(self._session).get(self._context.tenant_id)
        if tenant is None:
            raise _tenant_not_found()
        current = await self._repository.read()
        current_revision = 0 if current is None else current.revision
        if request.expected_revision != current_revision:
            raise _stale_revision()
        data = dict(request.data)
        # Existing panel forms do not submit a model selector. An unrelated
        # greeting/tone edit must not silently reset an explicitly chosen model.
        if step == "agent" and current is not None and "model" not in data:
            data["model"] = current.configuration.agent.model
        model = _STEP_MODELS[step].model_validate(data)
        config = OnboardingConfiguration() if current is None else current.configuration
        updated = config.model_copy(update={_ATTRIBUTE_BY_STEP[step]: model}, deep=True)
        stored = await self._repository.save(
            configuration=updated,
            expected_revision=request.expected_revision,
        )
        if stored is None:
            raise _stale_revision()
        await AuditService(self._session).record(
            context=self._context,
            event_type="tenant.onboarding_step_saved",
            entity_type="tenant_onboarding",
            entity_id=self._context.tenant_id,
            payload={"step": step, "revision": stored.revision},
        )
        return _build_response(
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            revision=stored.revision,
            updated_at=stored.updated_at,
            config=stored.configuration,
            facts=await self._repository.domain_facts(code_digest=self._code_digest),
        )


def _build_response(
    *,
    tenant_id: UUID,
    tenant_name: str,
    revision: int,
    updated_at: datetime | None,
    config: OnboardingConfiguration,
    facts: DomainFacts,
) -> OnboardingResponse:
    steps: list[OnboardingStep] = []
    completed: set[StepKey] = set()

    def add(
        *,
        key: StepKey,
        title: str,
        instructions: str,
        required: list[str],
        missing: list[str],
        data: BaseModel | None = None,
        domain_blockers: list[str] | None = None,
        warnings: list[str] | None = None,
        tests: list[str] | None = None,
        dependencies: tuple[StepKey, ...] = (),
        fact_complete: bool = False,
    ) -> None:
        blockers = list(domain_blockers or [])
        for dependency in dependencies:
            if dependency not in completed:
                dependency_title = next(
                    item.title for item in steps if item.key == dependency
                )
                blockers.append(f"Completa primero: {dependency_title}.")
        has_data = data is not None and _has_non_default_data(data)
        if blockers:
            status: StepStatus = "BLOCKED"
        elif fact_complete or (not missing and (has_data or data is None)):
            status = "COMPLETE"
            completed.add(key)
        elif has_data:
            status = "IN_PROGRESS"
        else:
            status = "NOT_STARTED"
        steps.append(
            OnboardingStep(
                key=key,
                position=len(steps) + 1,
                title=title,
                instructions=instructions,
                status=status,
                required_fields=required,
                test_actions=list(tests or []),
                blockers=blockers + [f"Falta: {label}." for label in missing],
                warnings=list(warnings or []),
                documentation_links=_DOCS,
                data={} if data is None else data.model_dump(mode="json"),
            )
        )

    company_missing = _missing_strings(
        config.company,
        {
            "legal_name": "nombre legal",
            "commercial_name": "nombre comercial",
            "country": "país",
            "city": "ciudad",
            "industry": "industria",
            "business_description": "descripción del negocio",
            "service_hours": "horario de atención",
            "responsible_person": "responsable del negocio",
            "privacy_contact": "responsable de privacidad",
            "incident_contact": "responsable de incidentes",
        },
    )
    add(
        key="company",
        title="Company",
        instructions="Registra la identidad legal, ubicación, operación y responsables del cliente.",
        required=[
            "Identidad legal y comercial",
            "Ubicación, industria, zona horaria e idioma",
            "Descripción, horario y responsables",
        ],
        missing=company_missing,
        data=config.company,
        warnings=(
            [
                "El volumen de WhatsApp puede permanecer como desconocido durante el piloto."
            ]
            if config.company.whatsapp_volume == "unknown"
            else []
        ),
    )

    agent_missing = _missing_strings(
        config.agent,
        {"greeting": "saludo", "instructions": "instrucciones del agente"},
    )
    if "es-CO" not in config.agent.supported_languages:
        agent_missing.append("idioma principal es-CO")
    add(
        key="agent",
        title="Agent",
        instructions="Define nombre opcional, voz, trato, saludo e instrucciones dentro del alcance empresarial.",
        required=["Saludo", "Tono y formalidad", "Instrucciones", "Idiomas v1"],
        missing=agent_missing,
        data=config.agent,
        dependencies=("company",),
        warnings=(
            ["El agente no debe presentarse como una persona real."]
            if config.agent.agent_name
            else []
        ),
    )

    capability_blockers: list[str] = []
    available_capabilities = {
        manifest.stable_name for manifest in V1_CAPABILITY_REGISTRY.list()
    }
    unavailable = sorted(
        set[str](config.capabilities.selected_capabilities) - available_capabilities
    )
    if unavailable:
        capability_blockers.append(
            "Los Capability Packs seleccionados todavía no están registrados: "
            + ", ".join(unavailable)
            + "."
        )
    add(
        key="capabilities",
        title="Capabilities",
        instructions="Mapea los casos de uso a los Capability Packs v1 y clasifica cualquier necesidad no soportada.",
        required=["Al menos un caso de uso", "Clasificación Standard o Custom"],
        missing=[] if config.capabilities.use_cases else ["casos de uso"],
        data=config.capabilities,
        domain_blockers=capability_blockers,
        dependencies=("agent",),
    )

    connector_blockers: list[str] = []
    if (
        config.integrations.business_systems_required
        and not config.integrations.required_connectors
    ):
        connector_blockers.append("Selecciona los sistemas externos requeridos.")
    if config.integrations.required_connectors:
        connector_blockers.append(
            "Los conectores empresariales seleccionados aún no tienen una conexión saludable implementada."
        )
    integration_missing = (
        ["confirmación sobre sistemas externos"]
        if config.integrations.business_systems_required is None
        else []
    )
    add(
        key="integrations",
        title="Integrations",
        instructions="Declara únicamente los sistemas requeridos y verifica conexión, permisos y operaciones.",
        required=[
            "Confirmar si requiere sistemas externos",
            "Conectores saludables si aplican",
        ],
        missing=integration_missing,
        data=config.integrations,
        domain_blockers=connector_blockers,
        dependencies=("capabilities",),
        tests=["Probar conexión y permisos de cada conector requerido."],
    )

    knowledge_missing = _missing_strings(
        config.knowledge,
        {
            "source_name": "nombre de la fuente",
            "source_reference": "archivo, URL o referencia",
            "approved_summary": "contenido o resumen aprobado",
        },
    )
    knowledge_blockers: list[str] = []
    if not knowledge_missing and not facts.knowledge_frozen:
        knowledge_blockers.append(
            "Prepara el candidato para versionar el resumen aprobado; la referencia PDF o web no se importa automáticamente."
        )
    if config.knowledge.critical_conflicts > 0:
        knowledge_blockers.append(
            "Hay conflictos críticos de conocimiento sin resolver."
        )
    if not config.knowledge.review_confirmed and _has_non_default_data(
        config.knowledge
    ):
        knowledge_missing.append("confirmación de revisión")
    add(
        key="knowledge",
        title="Knowledge & Conflict Review",
        instructions="Registra fuentes aprobadas, autoridad, revisión y conflictos antes de generar conocimiento del agente.",
        required=[
            "Fuente aprobada",
            "Autoridad",
            "Revisión",
            "Cero conflictos críticos",
        ],
        missing=knowledge_missing,
        data=config.knowledge,
        domain_blockers=knowledge_blockers,
        dependencies=("integrations",),
        tests=["Verificar procedencia y resolver conflictos críticos."],
    )

    policy_missing: list[str] = []
    if config.policies_identity.pricing_response is None:
        policy_missing.append("regla para comunicar precios")
    if config.policies_identity.privacy_policy_status is None:
        policy_missing.append("estado de la política de privacidad")
    if config.policies_identity.customer_identity_method is None:
        policy_missing.append("método de identidad")
    add(
        key="policies-identity",
        title="Policies & Identity",
        instructions="Configura reglas comerciales e identidad sin debilitar los mínimos de seguridad de la plataforma.",
        required=["Precios", "Privacidad", "Método de identidad"],
        missing=policy_missing,
        data=config.policies_identity,
        dependencies=("knowledge",),
        warnings=(
            ["La política de privacidad aún no está aprobada."]
            if config.policies_identity.privacy_policy_status != "APPROVED"
            else []
        ),
    )

    human_missing = (
        ["decisión sobre Live Human Handoff"]
        if config.human_operations.handoff_enabled is None
        else []
    )
    human_blockers: list[str] = []
    if (
        config.human_operations.handoff_enabled
        and config.human_operations.response_surface == "NONE"
    ):
        human_blockers.append(
            "Live Human Handoff requiere Coexistence o una bandeja externa compatible."
        )
    add(
        key="human-operations",
        title="Human Operations",
        instructions="Decide si habrá atención humana y valida una superficie real antes de activarla.",
        required=["Decisión de handoff", "Superficie de respuesta si se habilita"],
        missing=human_missing,
        data=config.human_operations,
        domain_blockers=human_blockers,
        dependencies=("policies-identity",),
    )

    approval_missing = (
        ["decisión sobre acciones de alto riesgo"]
        if config.approval_routes.high_risk_actions_expected is None
        else []
    )
    approval_blockers: list[str] = []
    if (
        config.approval_routes.high_risk_actions_expected
        and not config.approval_routes.approver_emails
    ):
        approval_blockers.append("Agrega al menos un correo de aprobador autorizado.")
    invalid_emails = [
        value
        for value in config.approval_routes.approver_emails
        if "@" not in value or value.startswith("@") or value.endswith("@")
    ]
    if invalid_emails:
        approval_blockers.append("Corrige los correos de aprobadores no válidos.")
    if config.approval_routes.high_risk_actions_expected:
        approval_blockers.append(
            "El flujo seguro de aprobación por enlace y OTP aún no está conectado."
        )
    add(
        key="approval-routes",
        title="Approval Routes",
        instructions="Define responsables de acciones de alto riesgo; v1 usa la primera respuesta válida.",
        required=["Decisión sobre alto riesgo", "Aprobadores si aplican"],
        missing=approval_missing,
        data=config.approval_routes,
        domain_blockers=approval_blockers,
        dependencies=("human-operations",),
        tests=["Probar enlace, OTP, primera respuesta y notificación al cliente."],
    )

    whatsapp_blockers: list[str] = []
    if not facts.whatsapp_configured:
        whatsapp_blockers.append("Conecta un número mediante Meta Embedded Signup.")
    elif not facts.healthy_whatsapp:
        whatsapp_blockers.append("La cuenta de WhatsApp no está saludable.")
    add(
        key="whatsapp",
        title="WhatsApp",
        instructions="Conecta el número del cliente y verifica mapeo, webhooks, plantillas y entrega.",
        required=["Cuenta activa y saludable"],
        missing=[],
        domain_blockers=whatsapp_blockers,
        dependencies=("approval-routes",),
        fact_complete=facts.healthy_whatsapp,
        tests=["Probar un mensaje entrante y uno saliente observable."],
    )

    test_complete = facts.test_checks_passed
    add(
        key="test",
        title="Test",
        instructions="Ejecuta escenarios representativos y promueve únicamente el AgentSpec exacto que pasó.",
        required=[
            "AgentSpec compilado en estado Test",
            "Escenarios representativos aprobados",
        ],
        missing=[],
        domain_blockers=(
            []
            if test_complete
            else ["Prepara un candidato y ejecuta sus pruebas antes de continuar."]
        ),
        dependencies=("whatsapp",),
        fact_complete=test_complete,
        tests=["Ejecutar el Eval Runner sobre el digest exacto del candidato."],
    )

    add(
        key="quality-gate",
        title="Quality Gate",
        instructions="Verifica evidencia persistida para los digests exactos de AgentSpec, conocimiento y código.",
        required=["Decisión aprobada y vigente del Quality Gate"],
        missing=[],
        domain_blockers=[]
        if facts.quality_gate_passed
        else ["Falta revisar y aprobar pruebas vigentes de la versión exacta."],
        dependencies=("test",),
        fact_complete=facts.quality_gate_passed,
    )

    add(
        key="production",
        title="Production",
        instructions="Publica explícitamente la versión exacta aprobada y conserva un rollback verificable.",
        required=[
            "Quality Gate vigente",
            "Despliegue explícito",
            "Rollback disponible",
        ],
        missing=[],
        domain_blockers=(
            []
            if facts.production_deployed
            else ["No hay un AgentSpec desplegado en Production."]
        ),
        dependencies=("quality-gate",),
        fact_complete=facts.production_deployed,
    )

    first_open = next(
        (step.key for step in steps if step.status != "COMPLETE"), "production"
    )
    return OnboardingResponse(
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        revision=revision,
        updated_at=updated_at,
        current_step=cast(StepKey, first_open),
        completed_steps=sum(step.status == "COMPLETE" for step in steps),
        steps=steps,
    )


def _has_non_default_data(model: BaseModel) -> bool:
    default = type(model)()
    return model.model_dump(mode="json") != default.model_dump(mode="json")


def _missing_strings(model: BaseModel, fields: dict[str, str]) -> list[str]:
    return [label for name, label in fields.items() if not getattr(model, name)]


def _tenant_not_found() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/tenant-not-found",
        title="Tenant Not Found",
        status=404,
        detail="The requested tenant does not exist.",
        code="tenant_not_found",
    )


def _stale_revision() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/stale-onboarding-revision",
        title="Stale Onboarding Revision",
        status=409,
        detail="The onboarding configuration changed in another session. Reload it before saving.",
        code="stale_onboarding_revision",
    )


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/onboarding",
    tags=["platform-admin-tenant-onboarding"],
)


@router.get("", response_model=OnboardingResponse)
async def read_onboarding(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> OnboardingResponse:
    return await _service(request, principal, tenant_id, session).read()


@router.patch("/{step}", response_model=OnboardingResponse)
async def update_onboarding_step(
    tenant_id: UUID,
    step: EditableStepKey,
    payload: UpdateOnboardingStepRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> OnboardingResponse:
    return await _service(request, principal, tenant_id, session).update(
        step=step,
        request=payload,
    )


def _service(
    request: Request,
    principal: AdminPrincipal,
    tenant_id: UUID,
    session: AsyncSession,
) -> OnboardingService:
    return OnboardingService(
        session,
        TenantContext(
            tenant_id=tenant_id,
            actor_id=principal.user_id,
            actor_type="platform_admin",
            correlation_id=request.state.correlation_id,
        ),
        code_digest=request.app.state.settings.agent_publication_code_digest,
    )
