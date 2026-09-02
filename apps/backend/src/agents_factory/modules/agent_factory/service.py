from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from agents_factory.common.errors import DomainError
from agents_factory.modules.agent_factory.compiler import (
    AgentSpecCompiler,
    AgentSpecValidator,
)
from agents_factory.modules.agent_factory.models import (
    AgentInstance,
    AgentSpecConfiguration,
    AgentSpecVersion,
    HumanOperationsConfiguration,
    LanguagePolicy,
    PersonaConfiguration,
    Sha256Digest,
    VersionedDigestReference,
    VersionReference,
)
from agents_factory.modules.agent_factory.repository import AgentSpecRepository
from agents_factory.modules.agent_factory.schemas import (
    AgentEditorState,
    AgentEditorVersion,
    AgentPresentationUpdateRequest,
)
from agents_factory.modules.runtime.customer_service.quick_options import (
    build_quick_options,
)


@dataclass(frozen=True, slots=True)
class QualityGateEvidence:
    decision_id: UUID
    passed: bool
    agent_spec_digest: Sha256Digest
    knowledge_digest: Sha256Digest
    code_digest: Sha256Digest


class ProductionQualityGate(Protocol):
    async def evaluate(
        self,
        *,
        agent_spec_digest: str,
        knowledge_digest: str,
        code_digest: str,
    ) -> QualityGateEvidence | None: ...


class FailClosedProductionQualityGate:
    """Task 45 replaces this port with persisted exact-digest evidence."""

    async def evaluate(
        self,
        *,
        agent_spec_digest: str,
        knowledge_digest: str,
        code_digest: str,
    ) -> None:
        _ = (agent_spec_digest, knowledge_digest, code_digest)
        return None


class AgentSpecLifecycleService:
    def __init__(
        self,
        *,
        repository: AgentSpecRepository,
        quality_gate: ProductionQualityGate | None = None,
        manifest_validator: AgentSpecValidator | None = None,
    ) -> None:
        self._repository = repository
        self._compiler = AgentSpecCompiler(repository, validator=manifest_validator)
        self._quality_gate = quality_gate or FailClosedProductionQualityGate()

    async def create_instance(
        self, *, configuration: AgentSpecConfiguration
    ) -> tuple[AgentInstance, AgentSpecVersion]:
        instance = await self._repository.create_instance()
        draft = await self._repository.create_draft(
            agent_instance_id=instance.id,
            configuration=configuration,
            based_on_version_id=None,
        )
        return instance, draft

    async def create_customer_service_draft(
        self, *, business_name: str
    ) -> tuple[AgentInstance, AgentSpecVersion]:
        if await self._repository.primary_instance() is not None:
            raise DomainError(
                type="https://agents-factory.dev/problems/agent-instance-exists",
                title="Agent Already Configured",
                status=409,
                detail="This tenant already has a Customer Service Agent.",
                code="agent_instance_exists",
            )
        return await self.create_instance(
            configuration=_default_configuration(business_name=business_name)
        )

    async def editor_state(self) -> AgentEditorState | None:
        instance = await self._repository.primary_instance()
        if instance is None:
            return None
        latest = await self._repository.latest_version(agent_instance_id=instance.id)
        if latest is None:
            raise RuntimeError("Agent Instance has no AgentSpec version")
        production = await self._repository.active_version(
            agent_instance_id=instance.id
        )
        language: Literal["es", "en"] = (
            "en" if latest.configuration.language.default_locale == "en-US" else "es"
        )
        return AgentEditorState(
            instance=instance,
            editable_version=latest,
            production_version=(
                None
                if production is None
                else AgentEditorVersion(
                    id=production.id,
                    version_number=production.version_number,
                    state=production.state,
                    created_at=production.created_at,
                )
            ),
            quick_options=build_quick_options(
                active_capabilities=frozenset(
                    reference.name for reference in latest.configuration.capabilities
                ),
                language=language,
                handoff_enabled=(latest.configuration.human_operations.handoff_enabled),
                handoff_surface_available=(
                    latest.configuration.human_operations.handoff_surface_available
                ),
            ),
        )

    async def create_presentation_draft(
        self,
        *,
        agent_instance_id: UUID,
        update: AgentPresentationUpdateRequest,
    ) -> AgentSpecVersion:
        instance = await self._repository.get_instance(agent_instance_id)
        base = await self._repository.get_version(update.expected_version_id)
        if (
            instance is None
            or base is None
            or base.agent_instance_id != agent_instance_id
        ):
            raise _not_found()

        persona_values = base.configuration.persona.model_dump()
        for field in ("agent_name", "tone", "formality", "greeting"):
            value = getattr(update, field)
            if value is not None:
                persona_values[field] = value.strip() or None
        if update.brand_vocabulary is not None:
            persona_values["brand_vocabulary"] = tuple(
                value.strip() for value in update.brand_vocabulary
            )
        persona_values["version"] = str(base.version_number + 1)

        language_values = base.configuration.language.model_dump()
        if update.supported_locales is not None:
            language_values["supported_locales"] = update.supported_locales
        if update.default_locale is not None:
            language_values["default_locale"] = update.default_locale

        configuration = base.configuration.model_copy(
            update={
                "persona": PersonaConfiguration.model_validate(persona_values),
                "language": LanguagePolicy.model_validate(language_values),
            }
        )
        created = await self._repository.create_draft_from_latest(
            agent_instance_id=agent_instance_id,
            expected_latest_version_id=update.expected_version_id,
            configuration=configuration,
        )
        if created is None:
            raise DomainError(
                type="https://agents-factory.dev/problems/agent-spec-stale-write",
                title="Agent Configuration Changed",
                status=409,
                detail="The Agent Draft changed. Reload it before saving again.",
                code="agent_spec_stale_write",
            )
        return created

    async def create_draft(
        self,
        *,
        agent_instance_id: UUID,
        based_on_version_id: UUID,
        configuration: AgentSpecConfiguration,
    ) -> AgentSpecVersion:
        instance = await self._repository.get_instance(agent_instance_id)
        base = await self._repository.get_version(based_on_version_id)
        if (
            instance is None
            or base is None
            or base.agent_instance_id != agent_instance_id
        ):
            raise _not_found()
        return await self._repository.create_draft(
            agent_instance_id=agent_instance_id,
            configuration=configuration,
            based_on_version_id=based_on_version_id,
        )

    async def promote_to_test(self, version_id: UUID) -> AgentSpecVersion:
        version = await self._required(version_id)
        if version.state != "DRAFT":
            raise _invalid_transition(version.state, "TEST")
        knowledge = version.configuration.knowledge
        if not await self._repository.has_deployable_knowledge_binding(
            name=knowledge.name,
            version=knowledge.version,
            digest=knowledge.digest,
        ):
            raise DomainError(
                type=(
                    "https://agents-factory.dev/problems/"
                    "agent-spec-knowledge-binding-required"
                ),
                title="Deployable Knowledge Binding Required",
                status=409,
                detail=(
                    "AgentSpec requires an exact immutable Test or Production "
                    "Knowledge version binding."
                ),
                code="agent_spec_knowledge_binding_required",
            )
        compiled = await self._compiler.compile(version.agent_instance_id, version.id)
        promoted = await self._repository.promote_draft_to_test(
            version_id=version.id,
            compiled=compiled,
        )
        if promoted is None:
            raise _invalid_transition(version.state, "TEST")
        return promoted

    async def enter_quality_gate(self, version_id: UUID) -> AgentSpecVersion:
        version = await self._required(version_id)
        if version.state != "TEST":
            raise _invalid_transition(version.state, "QUALITY_GATE")
        entered = await self._repository.enter_quality_gate(version_id)
        if entered is None:
            raise _invalid_transition(version.state, "QUALITY_GATE")
        return entered

    async def publish_production(self, version_id: UUID) -> AgentSpecVersion:
        version = await self._required(version_id)
        if (
            version.state != "QUALITY_GATE"
            or version.compiled_digest is None
            or version.compiled_spec is None
        ):
            raise _invalid_transition(version.state, "PRODUCTION")
        expected = (
            version.compiled_digest,
            version.configuration.knowledge.digest,
            version.configuration.code_digest,
        )
        evidence = await self._quality_gate.evaluate(
            agent_spec_digest=expected[0],
            knowledge_digest=expected[1],
            code_digest=expected[2],
        )
        if (
            evidence is None
            or not evidence.passed
            or (
                evidence.agent_spec_digest,
                evidence.knowledge_digest,
                evidence.code_digest,
            )
            != expected
        ):
            raise DomainError(
                type="https://agents-factory.dev/problems/quality-gate-required",
                title="Production Quality Gate Required",
                status=409,
                detail="Exact-digest Production Quality Gate evidence is required.",
                code="production_quality_gate_required",
            )
        published = await self._repository.publish(
            version_id=version_id,
            decision_id=evidence.decision_id,
            published_at=datetime.now(UTC),
        )
        if published is None:
            raise _invalid_transition(version.state, "PRODUCTION")
        return published

    async def rollback_to(
        self,
        *,
        agent_instance_id: UUID,
        target_version_id: UUID,
        current_code_digest: str,
    ) -> AgentSpecVersion:
        target = await self._required(target_version_id)
        active = await self._repository.active_version(
            agent_instance_id=agent_instance_id
        )
        evidence = await self._repository.original_deployment(version_id=target.id)
        if (
            target.agent_instance_id != agent_instance_id
            or target.state != "PRODUCTION"
            or target.configuration.code_digest != current_code_digest
            or evidence is None
        ):
            raise DomainError(
                type="https://agents-factory.dev/problems/incompatible-agent-spec-rollback",
                title="Incompatible AgentSpec Rollback",
                status=409,
                detail="The target is not a previously valid compatible Production version.",
                code="incompatible_agent_spec_rollback",
            )
        await self._repository.append_deployment(
            version=target,
            action="ROLLBACK",
            decision_id=evidence.quality_gate_decision_id,
            replaced_version_id=None if active is None else active.id,
            created_at=datetime.now(UTC),
        )
        return target

    async def _required(self, version_id: UUID) -> AgentSpecVersion:
        version = await self._repository.get_version(version_id)
        if version is None:
            raise _not_found()
        return version


def _not_found() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/agent-spec-not-found",
        title="AgentSpec Not Found",
        status=404,
        detail="The requested AgentSpec resource does not exist.",
        code="agent_spec_not_found",
    )


def _invalid_transition(current: str, target: str) -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/invalid-agent-spec-transition",
        title="Invalid AgentSpec Transition",
        status=409,
        detail=f"AgentSpec cannot transition from {current} to {target}.",
        code="invalid_agent_spec_transition",
    )


def _default_configuration(*, business_name: str) -> AgentSpecConfiguration:
    return AgentSpecConfiguration(
        product_version="1.0.0",
        persona=PersonaConfiguration(
            version="1",
            business_name=business_name.strip(),
            instructions=(
                "Representa a la empresa con claridad, empatía y precisión. "
                "Usa únicamente información y acciones habilitadas."
            ),
        ),
        policy=VersionReference(name="customer_service", version="1"),
        identity_policy=VersionReference(name="standard", version="1"),
        approval_routes=VersionReference(name="standard", version="1"),
        knowledge=VersionedDigestReference(
            name="tenant_knowledge", version="0", digest="0" * 64
        ),
        human_operations=HumanOperationsConfiguration(
            version="1", handoff_enabled=False, handoff_surface_available=False
        ),
        code_digest="0" * 64,
    )
