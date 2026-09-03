from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]
IdentityLevel = Literal[0, 1, 2, 3]
_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?"
)
_STABLE_NAME = re.compile(r"[a-z][a-z0-9_]*")
_OPERATION = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")


class FrozenManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActionDefinition(FrozenManifest):
    name: str = Field(pattern=_OPERATION.pattern)
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    risk: RiskLevel
    required_identity_level: IdentityLevel
    requires_confirmation: bool
    requires_approval: bool
    failure_behavior: str = Field(min_length=1, max_length=500)
    handoff_behavior: str = Field(min_length=1, max_length=500)
    eval_case_ids: tuple[str, ...] = Field(min_length=1)
    required_connector_operations: tuple[str, ...] = ()
    connector_requirement_mode: Literal["single_binding", "all_bindings", "none"] = (
        "single_binding"
    )

    @model_validator(mode="after")
    def valid_connector_requirements(self) -> Self:
        if (
            self.connector_requirement_mode == "none"
            and self.required_connector_operations
        ):
            raise ValueError("internal actions cannot require connector operations")
        if (
            self.connector_requirement_mode == "all_bindings"
            and not self.required_connector_operations
        ):
            raise ValueError("multi-binding actions must declare connector operations")
        if len(set(self.required_connector_operations)) != len(
            self.required_connector_operations
        ) or any(
            not _OPERATION.fullmatch(name)
            for name in self.required_connector_operations
        ):
            raise ValueError(
                "connector requirements must be unique qualified operations"
            )
        return self


class CapabilityManifest(FrozenManifest):
    stable_name: str = Field(pattern=_STABLE_NAME.pattern)
    version: str = Field(pattern=_SEMVER.pattern)
    intents: tuple[str, ...] = Field(min_length=1)
    workflow: tuple[str, ...] = Field(min_length=1)
    business_schemas: dict[str, dict[str, object]]
    actions: tuple[ActionDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        action_names = [action.name for action in self.actions]
        if len(set(action_names)) != len(action_names):
            raise ValueError("capability actions must be unique")
        if any(name.partition(".")[0] != self.stable_name for name in action_names):
            raise ValueError("capability action names must use the capability prefix")
        if not self.business_schemas:
            raise ValueError("capability business schemas are required")
        return self


class TenantExtensionManifest(FrozenManifest):
    stable_name: str = Field(pattern=_STABLE_NAME.pattern)
    version: str = Field(pattern=_SEMVER.pattern)
    owner: str = Field(min_length=1, max_length=200)
    platform_compatibility: str = Field(min_length=1, max_length=100)
    isolated_tests: tuple[str, ...] = Field(min_length=1)
    enabled: bool = False
    deployment_artifact: str = Field(min_length=1, max_length=500)
    rollback_target: str = Field(min_length=1, max_length=500)
    entry_point: str = Field(min_length=1, max_length=300)
