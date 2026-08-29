from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
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
    Sha256Digest,
)
from agents_factory.modules.agent_factory.repository import AgentSpecRepository


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
