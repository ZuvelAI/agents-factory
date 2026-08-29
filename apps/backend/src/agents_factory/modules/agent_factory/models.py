from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
from sqlalchemy.engine import RowMapping

from agents_factory.modules.runtime.contracts import (
    AgentSpecSnapshot,
    ModelConfiguration as RuntimeModelConfiguration,
    RuntimeLimits as RuntimeSnapshotLimits,
)


AgentSpecState = Literal["DRAFT", "TEST", "QUALITY_GATE", "PRODUCTION"]
DeploymentAction = Literal["PUBLISH", "ROLLBACK"]
_DIGEST = re.compile(r"[0-9a-f]{64}")
_QUALIFIED_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")


def _valid_digest(value: str) -> str:
    if not _DIGEST.fullmatch(value):
        raise ValueError("digest must be lowercase SHA-256")
    return value


Sha256Digest = Annotated[str, AfterValidator(_valid_digest)]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VersionReference(FrozenModel):
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=100)


class VersionedDigestReference(VersionReference):
    digest: Sha256Digest


class PersonaConfiguration(FrozenModel):
    version: str = Field(min_length=1, max_length=100)
    business_name: str = Field(
        default="Configured Business", min_length=1, max_length=200
    )
    instructions: str = Field(min_length=1, max_length=50_000)


class ConnectorBinding(FrozenModel):
    binding_id: UUID
    connector: str = Field(min_length=1, max_length=120)
    connector_version: str = Field(min_length=1, max_length=100)
    operations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_operations(self) -> Self:
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("connector operations must be unique")
        if any(not _QUALIFIED_NAME.fullmatch(value) for value in self.operations):
            raise ValueError("connector operations must be capability-qualified")
        return self


class AgentModelConfiguration(FrozenModel):
    model: Literal["gpt-5.6-luna"] = "gpt-5.6-luna"
    reasoning_effort: Literal["low"] = "low"


class LanguagePolicy(FrozenModel):
    supported_locales: tuple[Literal["es-CO"], Literal["en-US"]] = (
        "es-CO",
        "en-US",
    )
    default_locale: Literal["es-CO"] = "es-CO"


class HumanOperationsConfiguration(FrozenModel):
    version: str = Field(min_length=1, max_length=100)
    handoff_enabled: bool = True
    handoff_surface_available: bool = False
    awaiting_human_policy: Literal["SILENT", "ACKNOWLEDGE"] = "SILENT"


class AgentRuntimeLimits(FrozenModel):
    max_output_tokens: int = Field(default=2_048, ge=1, le=16_384)
    max_tool_calls: int = Field(default=8, ge=0, le=32)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)


class AgentSpecConfiguration(FrozenModel):
    product_version: str = Field(min_length=1, max_length=100)
    persona: PersonaConfiguration
    capabilities: tuple[VersionReference, ...] = ()
    permitted_tools: tuple[str, ...] = ()
    permitted_actions: tuple[str, ...] = ()
    connector_bindings: tuple[ConnectorBinding, ...] = ()
    policy: VersionReference
    identity_policy: VersionReference
    approval_routes: VersionReference
    knowledge: VersionedDigestReference
    model: AgentModelConfiguration = Field(default_factory=AgentModelConfiguration)
    language: LanguagePolicy = Field(default_factory=LanguagePolicy)
    human_operations: HumanOperationsConfiguration
    runtime_limits: AgentRuntimeLimits = Field(default_factory=AgentRuntimeLimits)
    code_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_collections(self) -> Self:
        for values, label in (
            (self.permitted_tools, "tools"),
            (self.permitted_actions, "actions"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"permitted {label} must be unique")
            if any(not _QUALIFIED_NAME.fullmatch(value) for value in values):
                raise ValueError(f"permitted {label} must be capability-qualified")
        capability_names = [item.name for item in self.capabilities]
        if len(set(capability_names)) != len(capability_names):
            raise ValueError("capability names must be unique")
        binding_ids = [item.binding_id for item in self.connector_bindings]
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError("connector binding IDs must be unique")
        return self


class AgentSpec(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    tenant_id: UUID
    agent_instance_id: UUID
    version_id: UUID
    version_number: int = Field(ge=1)
    product: Literal["Agent Customer Service"] = "Agent Customer Service"
    configuration: AgentSpecConfiguration

    def to_runtime_snapshot(self, *, active: bool) -> AgentSpecSnapshot:
        from agents_factory.modules.runtime.customer_service.instructions import (
            CustomerServiceInstructionsBuilder,
        )

        return AgentSpecSnapshot(
            id=self.version_id,
            tenant_id=self.tenant_id,
            version=str(self.version_number),
            digest=self.digest(),
            product=self.product,
            product_version=self.configuration.product_version,
            instructions=CustomerServiceInstructionsBuilder().build(spec=self),
            active_capabilities=frozenset(
                item.name for item in self.configuration.capabilities
            ),
            permitted_tools=frozenset(self.configuration.permitted_tools),
            model=RuntimeModelConfiguration(
                model=self.configuration.model.model,
                reasoning_effort=self.configuration.model.reasoning_effort,
            ),
            limits=RuntimeSnapshotLimits(
                max_output_tokens=self.configuration.runtime_limits.max_output_tokens,
                max_tool_calls=self.configuration.runtime_limits.max_tool_calls,
                timeout_seconds=self.configuration.runtime_limits.timeout_seconds,
            ),
            active=active,
        )

    def digest(self) -> str:
        from agents_factory.modules.agent_factory.compiler import canonical_json

        return canonical_json(self).digest


class AgentSpecDraft(FrozenModel):
    id: UUID
    tenant_id: UUID
    agent_instance_id: UUID
    version_number: int = Field(ge=1)
    based_on_version_id: UUID | None = None
    configuration: AgentSpecConfiguration


class AgentSpecVersion(FrozenModel):
    id: UUID
    tenant_id: UUID
    agent_instance_id: UUID
    version_number: int
    state: AgentSpecState
    based_on_version_id: UUID | None
    configuration: AgentSpecConfiguration
    compiled_spec: AgentSpec | None
    compiled_digest: Sha256Digest | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        compiled = row["compiled_spec"]
        return cls(
            id=row["id"],
            tenant_id=row["tenant_id"],
            agent_instance_id=row["agent_instance_id"],
            version_number=row["version_number"],
            state=row["state"],
            based_on_version_id=row["based_on_version_id"],
            configuration=AgentSpecConfiguration.model_validate(row["configuration"]),
            compiled_spec=(
                None if compiled is None else AgentSpec.model_validate(compiled)
            ),
            compiled_digest=row["compiled_digest"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def as_draft(self) -> AgentSpecDraft:
        return AgentSpecDraft(
            id=self.id,
            tenant_id=self.tenant_id,
            agent_instance_id=self.agent_instance_id,
            version_number=self.version_number,
            based_on_version_id=self.based_on_version_id,
            configuration=self.configuration,
        )


class AgentInstance(FrozenModel):
    id: UUID
    tenant_id: UUID
    product: Literal["Agent Customer Service"] = "Agent Customer Service"
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls(
            id=row["id"],
            tenant_id=row["tenant_id"],
            product=row["product"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class AgentSpecDeployment(FrozenModel):
    id: UUID
    tenant_id: UUID
    agent_instance_id: UUID
    version_id: UUID
    action: DeploymentAction
    replaced_version_id: UUID | None
    agent_spec_digest: Sha256Digest
    knowledge_digest: Sha256Digest
    code_digest: Sha256Digest
    quality_gate_decision_id: UUID
    created_at: datetime
