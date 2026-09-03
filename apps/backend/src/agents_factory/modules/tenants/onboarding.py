from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.modules.agent_factory.models import AgentSpecConfiguration
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.capabilities.registry import V1_CAPABILITY_REGISTRY
from agents_factory.modules.tenants.repository import TenantRepository


OnboardingStepStatus = Literal[
    "COMPLETE", "READY", "BLOCKED", "ATTENTION", "STALE", "UNAVAILABLE"
]
OnboardingClassification = Literal[
    "STANDARD", "CUSTOM_CONNECTOR", "CUSTOM_WORKFLOW", "NEW_CAPABILITY"
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OnboardingMessage(FrozenModel):
    code: str
    message: str


class OnboardingAction(FrozenModel):
    label: str
    href: str
    available: bool


class OnboardingDocumentation(FrozenModel):
    label: str
    href: str


class OnboardingStep(FrozenModel):
    number: int
    slug: str
    name: str
    instructions: tuple[str, ...]
    required_fields: tuple[str, ...]
    validations: tuple[str, ...]
    status: OnboardingStepStatus
    blockers: tuple[OnboardingMessage, ...]
    warnings: tuple[OnboardingMessage, ...]
    test_actions: tuple[OnboardingAction, ...]
    documentation: tuple[OnboardingDocumentation, ...]


class OnboardingStatus(FrozenModel):
    tenant_id: UUID
    agent_instance_id: UUID | None
    agent_version_id: UUID | None
    agent_version_number: int | None
    complete_steps: int
    current_step_slug: str
    classifications: tuple[OnboardingClassification, ...]
    steps: tuple[OnboardingStep, ...]


@dataclass(frozen=True, slots=True)
class OnboardingFacts:
    tenant_id: UUID
    company_complete: bool
    agent_instance_id: UUID | None = None
    agent_version_id: UUID | None = None
    agent_version_number: int | None = None
    agent_state: str | None = None
    capability_names: tuple[str, ...] = ()
    integrations_required: bool = False
    connector_binding_count: int = 0
    healthy_connector_binding_count: int = 0
    knowledge_binding_valid: bool = False
    pending_knowledge_reviews: int = 0
    policy_configured: bool = False
    identity_policy_configured: bool = False
    handoff_enabled: bool = False
    human_surface_ready: bool = False
    required_approval_actions: tuple[str, ...] = ()
    configured_approval_actions: tuple[str, ...] = ()
    whatsapp_connected: bool = False
    whatsapp_healthy: bool = False
    has_tested_version: bool = False


@dataclass(frozen=True, slots=True)
class StepDefinition:
    slug: str
    name: str
    instructions: tuple[str, ...]
    required_fields: tuple[str, ...]
    validations: tuple[str, ...]
    action_label: str
    action_suffix: str
    documentation_label: str
    documentation_path: str


_DOCS_ROOT = "https://github.com/ZuvelAI/agents-factory/blob/main/"
CLASSIFICATIONS: tuple[OnboardingClassification, ...] = (
    "STANDARD",
    "CUSTOM_CONNECTOR",
    "CUSTOM_WORKFLOW",
    "NEW_CAPABILITY",
)
STEP_DEFINITIONS = (
    StepDefinition(
        "company",
        "Company",
        ("Confirm the client's legal identity and regional defaults.",),
        ("Display name", "Legal name", "Industry", "Timezone", "Locale"),
        ("Required fields are present.", "Timezone uses a valid IANA name."),
        "Review company profile",
        "/settings",
        "Client onboarding architecture",
        "docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md",
    ),
    StepDefinition(
        "agent",
        "Agent",
        ("Create the Customer Service Agent and review its business presentation.",),
        ("Agent Draft", "Name", "Tone", "Greeting", "Approved languages"),
        ("An immutable AgentSpec version exists.", "Only v1 languages are enabled."),
        "Review Agent Draft",
        "/agent",
        "AgentSpec and Customer Service Core",
        "docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md",
    ),
    StepDefinition(
        "capabilities",
        "Capabilities",
        (
            "Enable only approved v1 Capability Packs.",
            "Classify unsupported needs before promising custom work.",
        ),
        ("At least one Capability Pack", "Permitted operations"),
        (
            "Capability versions exist in the v1 registry.",
            "Operations stay manifest-bound.",
        ),
        "Review capabilities",
        "/capabilities",
        "Tenant extension boundary",
        "docs/architecture/tenant-extensions.md",
    ),
    StepDefinition(
        "integrations",
        "Integrations",
        ("Connect and health-check every provider required by enabled operations.",),
        ("Connector authorization", "Operation binding", "Health result"),
        ("Every required binding is connected and healthy.",),
        "Review integrations",
        "/integrations",
        "Connection lifecycle",
        "docs/integrations/connection-lifecycle.md",
    ),
    StepDefinition(
        "knowledge-conflict-review",
        "Knowledge & Conflict Review",
        ("Review sources, AI proposals and conflicts before binding knowledge.",),
        ("Deployable knowledge version", "Resolved reviews", "Exact digest"),
        (
            "The exact Test/Production knowledge digest exists.",
            "No review remains open.",
        ),
        "Review knowledge",
        "/knowledge",
        "Knowledge architecture",
        "docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md",
    ),
    StepDefinition(
        "policies-identity",
        "Policies & Identity",
        ("Review action policies and identity levels inherited by this Agent Draft.",),
        ("Policy version", "Identity policy version"),
        ("Both immutable references are present in the AgentSpec.",),
        "Review policies and identity",
        "/capabilities",
        "Capability risk and identity rules",
        "docs/capabilities/orders.md",
    ),
    StepDefinition(
        "human-operations",
        "Human Operations",
        (
            "Choose whether handoff is disabled or bind it to a verified response surface.",
        ),
        ("Handoff decision", "Response surface when enabled"),
        ("Enabled handoff has a persisted, available surface.",),
        "Review human operations",
        "/settings",
        "Human handoff operations",
        "docs/handoffs.md",
    ),
    StepDefinition(
        "approval-routes",
        "Approval Routes",
        ("Assign verified approvers for every enabled action that requires approval.",),
        ("Approval route", "Authorized recipients", "Enabled state"),
        ("Every approval-required action has an enabled route.",),
        "Review approval routes",
        "/capabilities",
        "Approval controls",
        "docs/approvals.md",
    ),
    StepDefinition(
        "whatsapp",
        "WhatsApp",
        ("Authorize the client's own WhatsApp business and confirm channel health.",),
        ("Active WhatsApp account", "Healthy provider check"),
        ("The verified tenant-number mapping is active and healthy.",),
        "Open WhatsApp setup",
        "/whatsapp",
        "WhatsApp onboarding architecture",
        "docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md",
    ),
    StepDefinition(
        "test",
        "Test",
        ("Compile and test the exact current Agent and Knowledge configuration.",),
        ("Current AgentSpec in Test", "Exact knowledge digest"),
        ("No newer Draft exists after the tested version.",),
        "Review test candidate",
        "/test-console",
        "MS7 test checkpoint",
        "docs/implementation/ms7-progress.md",
    ),
    StepDefinition(
        "quality-gate",
        "Quality Gate",
        ("Production Quality Gate evidence must match the exact candidate digests.",),
        ("Persisted Task 45 decision", "Exact Agent/Knowledge/Code digests"),
        ("Task 45 must provide passing, non-stale evidence.",),
        "View Quality Gate dependency",
        "/agent",
        "Production Quality Gate plan",
        "docs/superpowers/plans/2026-08-12-agents-factory-v1.md",
    ),
    StepDefinition(
        "production",
        "Production",
        ("Publish only the exact candidate approved by the Production Quality Gate.",),
        ("Passing Quality Gate", "Explicit Production publication"),
        ("Production remains fail-closed until Task 45 and deployment hardening.",),
        "View Production dependency",
        "/agent",
        "Deployment plan",
        "docs/superpowers/plans/2026-08-12-agents-factory-v1.md",
    ),
)


class OnboardingStatusEngine:
    def evaluate(self, facts: OnboardingFacts) -> OnboardingStatus:
        states: list[
            tuple[
                OnboardingStepStatus,
                tuple[OnboardingMessage, ...],
                tuple[OnboardingMessage, ...],
            ]
        ] = []

        states.append(
            self._fact_state(
                facts.company_complete,
                "company_profile_incomplete",
                "Complete the company, legal, industry, timezone and locale fields.",
            )
        )
        states.append(
            self._dependent_fact_state(
                states[-1][0],
                facts.agent_instance_id is not None,
                "agent_missing",
                "Create the Customer Service Agent Draft.",
            )
        )
        states.append(
            self._dependent_fact_state(
                states[-1][0],
                bool(facts.capability_names),
                "capabilities_missing",
                "Enable at least one approved v1 Capability Pack.",
            )
        )

        if states[-1][0] != "COMPLETE":
            integration_state = self._blocked(
                "capabilities_required", "Complete Capabilities first."
            )
        elif not facts.integrations_required:
            integration_state = (
                "COMPLETE",
                (),
                (
                    OnboardingMessage(
                        code="no_business_connector_required",
                        message="Enabled operations do not require an external business connector.",
                    ),
                ),
            )
        elif facts.connector_binding_count == 0:
            integration_state = self._attention(
                "connector_binding_missing",
                "Bind every connector required by enabled operations.",
            )
        elif facts.healthy_connector_binding_count != facts.connector_binding_count:
            integration_state = self._attention(
                "connector_health_incomplete",
                "Every required connector binding must be healthy.",
            )
        else:
            integration_state = ("COMPLETE", (), ())
        states.append(integration_state)

        if states[-1][0] != "COMPLETE":
            knowledge_state = self._blocked(
                "integrations_required", "Complete Integrations first."
            )
        elif not facts.knowledge_binding_valid:
            knowledge_state = self._attention(
                "knowledge_binding_invalid",
                "Bind an exact Test or Production knowledge version.",
            )
        elif facts.pending_knowledge_reviews:
            knowledge_state = self._attention(
                "knowledge_review_pending",
                "Resolve every pending knowledge proposal, conflict and source diff.",
            )
        else:
            knowledge_state = ("COMPLETE", (), ())
        states.append(knowledge_state)

        policies_ready = facts.policy_configured and facts.identity_policy_configured
        states.append(
            self._dependent_fact_state(
                states[-1][0],
                policies_ready,
                "policies_identity_missing",
                "Bind policy and identity-policy versions to the Agent Draft.",
            )
        )

        if states[-1][0] != "COMPLETE":
            human_state = self._blocked(
                "policies_identity_required", "Complete Policies & Identity first."
            )
        elif not facts.handoff_enabled:
            human_state = (
                "COMPLETE",
                (),
                (
                    OnboardingMessage(
                        code="handoff_disabled",
                        message="Human handoff is explicitly disabled for this Draft.",
                    ),
                ),
            )
        elif facts.human_surface_ready:
            human_state = ("COMPLETE", (), ())
        else:
            human_state = self._attention(
                "human_surface_missing",
                "Enabled handoff requires a verified response surface.",
            )
        states.append(human_state)

        required_routes = set(facts.required_approval_actions)
        configured_routes = set(facts.configured_approval_actions)
        if states[-1][0] != "COMPLETE":
            approval_state = self._blocked(
                "human_operations_required", "Complete Human Operations first."
            )
        elif not required_routes:
            approval_state = (
                "COMPLETE",
                (),
                (
                    OnboardingMessage(
                        code="no_approval_action_enabled",
                        message="No enabled action currently requires an approval route.",
                    ),
                ),
            )
        elif required_routes <= configured_routes:
            approval_state = ("COMPLETE", (), ())
        else:
            approval_state = self._attention(
                "approval_route_missing",
                "Configure an enabled route for every approval-required action.",
            )
        states.append(approval_state)

        if states[-1][0] != "COMPLETE":
            whatsapp_state = self._blocked(
                "approval_routes_required", "Complete Approval Routes first."
            )
        elif not facts.whatsapp_connected:
            whatsapp_state = self._attention(
                "whatsapp_not_connected",
                "Connect the client's WhatsApp business and number.",
            )
        elif not facts.whatsapp_healthy:
            whatsapp_state = self._attention(
                "whatsapp_not_healthy", "Run a successful WhatsApp health check."
            )
        else:
            whatsapp_state = ("COMPLETE", (), ())
        states.append(whatsapp_state)

        if states[-1][0] != "COMPLETE":
            test_state = self._blocked("whatsapp_required", "Complete WhatsApp first.")
        elif facts.agent_state in {"TEST", "QUALITY_GATE", "PRODUCTION"}:
            test_state = ("COMPLETE", (), ())
        elif facts.has_tested_version:
            test_state = (
                "STALE",
                (
                    OnboardingMessage(
                        code="tested_candidate_stale",
                        message="A newer Agent Draft exists after the last tested version.",
                    ),
                ),
                (),
            )
        else:
            test_state = self._fact_state(
                False,
                "agent_test_required",
                "Promote and test the exact current Agent Draft.",
            )
        states.append(test_state)

        quality_blockers = [
            OnboardingMessage(
                code="production_quality_gate_task_45_required",
                message="Task 45 must persist exact-digest Production Quality Gate evidence.",
            )
        ]
        if test_state[0] != "COMPLETE":
            quality_blockers.insert(
                0,
                OnboardingMessage(
                    code="test_required",
                    message="Complete the current Test candidate first.",
                ),
            )
        states.append(("UNAVAILABLE", tuple(quality_blockers), ()))
        states.append(
            (
                "UNAVAILABLE",
                (
                    OnboardingMessage(
                        code="quality_gate_required",
                        message="Production requires the unavailable Task 45 Quality Gate.",
                    ),
                ),
                (),
            )
        )

        steps = tuple(
            self._step(facts.tenant_id, number, definition, *states[number - 1])
            for number, definition in enumerate(STEP_DEFINITIONS, start=1)
        )
        current = next(
            (step.slug for step in steps if step.status != "COMPLETE"), "production"
        )
        return OnboardingStatus(
            tenant_id=facts.tenant_id,
            agent_instance_id=facts.agent_instance_id,
            agent_version_id=facts.agent_version_id,
            agent_version_number=facts.agent_version_number,
            complete_steps=sum(step.status == "COMPLETE" for step in steps),
            current_step_slug=current,
            classifications=CLASSIFICATIONS,
            steps=steps,
        )

    @staticmethod
    def _step(
        tenant_id: UUID,
        number: int,
        definition: StepDefinition,
        status: OnboardingStepStatus,
        blockers: tuple[OnboardingMessage, ...],
        warnings: tuple[OnboardingMessage, ...],
    ) -> OnboardingStep:
        available = status not in {"BLOCKED", "UNAVAILABLE"}
        return OnboardingStep(
            number=number,
            slug=definition.slug,
            name=definition.name,
            instructions=definition.instructions,
            required_fields=definition.required_fields,
            validations=definition.validations,
            status=status,
            blockers=blockers,
            warnings=warnings,
            test_actions=(
                OnboardingAction(
                    label=definition.action_label,
                    href=f"/tenants/{tenant_id}{definition.action_suffix}",
                    available=available,
                ),
            ),
            documentation=(
                OnboardingDocumentation(
                    label=definition.documentation_label,
                    href=_DOCS_ROOT + definition.documentation_path,
                ),
            ),
        )

    @staticmethod
    def _fact_state(
        complete: bool, code: str, message: str
    ) -> tuple[
        OnboardingStepStatus,
        tuple[OnboardingMessage, ...],
        tuple[OnboardingMessage, ...],
    ]:
        return (
            ("COMPLETE", (), ())
            if complete
            else ("READY", (OnboardingMessage(code=code, message=message),), ())
        )

    @classmethod
    def _dependent_fact_state(
        cls, dependency: OnboardingStepStatus, complete: bool, code: str, message: str
    ) -> tuple[
        OnboardingStepStatus,
        tuple[OnboardingMessage, ...],
        tuple[OnboardingMessage, ...],
    ]:
        if dependency != "COMPLETE":
            return cls._blocked(
                "previous_step_required", "Complete the previous onboarding step first."
            )
        return cls._fact_state(complete, code, message)

    @staticmethod
    def _blocked(
        code: str, message: str
    ) -> tuple[
        OnboardingStepStatus,
        tuple[OnboardingMessage, ...],
        tuple[OnboardingMessage, ...],
    ]:
        return "BLOCKED", (OnboardingMessage(code=code, message=message),), ()

    @staticmethod
    def _attention(
        code: str, message: str
    ) -> tuple[
        OnboardingStepStatus,
        tuple[OnboardingMessage, ...],
        tuple[OnboardingMessage, ...],
    ]:
        return "ATTENTION", (OnboardingMessage(code=code, message=message),), ()


class OnboardingService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def status(self) -> OnboardingStatus:
        facts = await self._facts()
        return OnboardingStatusEngine().evaluate(facts)

    async def _facts(self) -> OnboardingFacts:
        tenant = await TenantRepository(self._session).get(self._context.tenant_id)
        if tenant is None:
            raise DomainError(
                type="https://agents-factory.dev/problems/tenant-not-found",
                title="Tenant Not Found",
                status=404,
                detail="The requested tenant does not exist.",
                code="tenant_not_found",
            )
        company_complete = all(
            (
                tenant.name,
                tenant.legal_name,
                tenant.industry,
                tenant.timezone,
                tenant.locale,
            )
        )
        agents = AgentSpecRepository(self._session, self._context)
        instance = await agents.primary_instance()
        if instance is None:
            return OnboardingFacts(
                tenant_id=tenant.id, company_complete=bool(company_complete)
            )
        version = await agents.latest_version(agent_instance_id=instance.id)
        if version is None:
            raise RuntimeError("Agent Instance has no AgentSpec version")
        configuration = version.configuration
        required_approval_actions, integrations_required = _manifest_requirements(
            configuration
        )
        binding_ids = tuple(
            binding.binding_id for binding in configuration.connector_bindings
        )
        healthy_bindings = 0
        if binding_ids:
            healthy_bindings = int(
                await self._session.scalar(
                    text(
                        "SELECT count(*) FROM public.integration_connections "
                        "WHERE tenant_id=:tenant AND id=ANY(CAST(:ids AS uuid[])) "
                        "AND status='CONNECTED' AND health_status='HEALTHY'"
                    ),
                    {"tenant": tenant.id, "ids": list(binding_ids)},
                )
                or 0
            )
        knowledge = configuration.knowledge
        knowledge_valid = bool(
            knowledge.version.isdecimal()
            and int(knowledge.version) > 0
            and await self._session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM public.knowledge_versions "
                    "WHERE tenant_id=:tenant AND name=:name "
                    "AND version_number=:version AND digest=:digest "
                    "AND state IN ('TEST','PRODUCTION'))"
                ),
                {
                    "tenant": tenant.id,
                    "name": knowledge.name,
                    "version": int(knowledge.version),
                    "digest": knowledge.digest,
                },
            )
        )
        pending_reviews = int(
            await self._session.scalar(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM public.knowledge_proposals WHERE tenant_id=:tenant AND state='PROPOSED') + "
                    "(SELECT count(*) FROM public.knowledge_conflicts WHERE tenant_id=:tenant AND state='OPEN') + "
                    "(SELECT count(*) FROM public.knowledge_source_diffs WHERE tenant_id=:tenant AND state='DETECTED')"
                ),
                {"tenant": tenant.id},
            )
            or 0
        )
        human_surface_ready = bool(
            await self._session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM public.handoff_configurations "
                    "WHERE tenant_id=:tenant AND configuration->>'enabled'='true' "
                    "AND configuration->'surface' IS NOT NULL)"
                ),
                {"tenant": tenant.id},
            )
        )
        route_rows = await self._session.execute(
            text(
                "SELECT action FROM public.approval_routes WHERE tenant_id=:tenant "
                "AND ref=:ref AND configuration->>'enabled'='true'"
            ),
            {"tenant": tenant.id, "ref": configuration.approval_routes.name},
        )
        configured_routes = tuple(sorted(set(route_rows.scalars())))
        whatsapp_connected, whatsapp_healthy = (
            await self._session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE status='active') > 0, "
                    "count(*) FILTER (WHERE status='active' AND health_status='HEALTHY') > 0 "
                    "FROM public.whatsapp_accounts WHERE tenant_id=:tenant"
                ),
                {"tenant": tenant.id},
            )
        ).one()
        has_tested = bool(
            await self._session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM public.agent_spec_versions "
                    "WHERE tenant_id=:tenant AND agent_instance_id=:instance "
                    "AND state IN ('TEST','QUALITY_GATE','PRODUCTION'))"
                ),
                {"tenant": tenant.id, "instance": instance.id},
            )
        )
        return OnboardingFacts(
            tenant_id=tenant.id,
            company_complete=bool(company_complete),
            agent_instance_id=instance.id,
            agent_version_id=version.id,
            agent_version_number=version.version_number,
            agent_state=version.state,
            capability_names=tuple(item.name for item in configuration.capabilities),
            integrations_required=integrations_required,
            connector_binding_count=len(binding_ids),
            healthy_connector_binding_count=healthy_bindings,
            knowledge_binding_valid=knowledge_valid,
            pending_knowledge_reviews=pending_reviews,
            policy_configured=bool(
                configuration.policy.name and configuration.policy.version
            ),
            identity_policy_configured=bool(
                configuration.identity_policy.name
                and configuration.identity_policy.version
            ),
            handoff_enabled=configuration.human_operations.handoff_enabled,
            human_surface_ready=human_surface_ready,
            required_approval_actions=required_approval_actions,
            configured_approval_actions=configured_routes,
            whatsapp_connected=bool(whatsapp_connected),
            whatsapp_healthy=bool(whatsapp_healthy),
            has_tested_version=has_tested,
        )


def _manifest_requirements(
    configuration: AgentSpecConfiguration,
) -> tuple[tuple[str, ...], bool]:
    permitted = set(configuration.permitted_actions)
    approvals: set[str] = set()
    integrations_required = False
    for reference in configuration.capabilities:
        manifest = V1_CAPABILITY_REGISTRY.get(reference.name, reference.version)
        for action in manifest.actions:
            if action.name not in permitted:
                continue
            if action.requires_approval:
                approvals.add(action.name)
            if action.required_connector_operations:
                integrations_required = True
    return tuple(sorted(approvals)), integrations_required
