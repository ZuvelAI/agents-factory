from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


GraderName = Literal[
    "response_exists",
    "selected_tools",
    "persisted_result",
    "credentials_absent",
    "policy_classification",
    "response_language",
    "truthful_disclosure",
    "appointment_behavior",
    "order_behavior",
]
PolicyClassification = Literal["IN_SCOPE", "REDIRECT", "SAFETY_INCIDENT"]
ResponseLanguage = Literal["es", "en"]
_CASE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,99}")
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")


class StrictEvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvalInputTurn(StrictEvalModel):
    message: str = Field(min_length=1, max_length=4_000)
    active_capabilities: tuple[str, ...]
    permitted_tools: tuple[str, ...]
    relevant_capabilities: tuple[str, ...]

    @field_validator("message")
    @classmethod
    def message_is_trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("message must be trimmed")
        return value

    @field_validator(
        "active_capabilities",
        "permitted_tools",
        "relevant_capabilities",
    )
    @classmethod
    def canonical_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))


class EvalToolFixture(StrictEvalModel):
    name: str
    capability: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict[str, object]
    active: bool = True

    @field_validator("name")
    @classmethod
    def valid_tool_name(cls, value: str) -> str:
        if not _TOOL_NAME.fullmatch(value):
            raise ValueError("tool name must be capability-qualified")
        return value


class AppointmentProbe(StrictEvalModel):
    operation: Literal[
        "appointments.check_availability",
        "appointments.create_appointment",
        "appointments.get_appointment",
        "appointments.reschedule_appointment",
        "appointments.request_cancellation",
    ]
    identity_level: int = Field(ge=0, le=3)
    confirmed: bool = False
    approved: bool = False


class OrderProbe(StrictEvalModel):
    operation: str = Field(pattern=r"^orders\.[a-z_]+$")
    identity_level: int = Field(ge=0, le=3)
    confirmed: bool = False
    approved: bool = False
    supported: bool = True
    issue: dict[str, object] | None = None


class EvalFixtureSetup(StrictEvalModel):
    fake_outputs: tuple[str, ...]
    tools: tuple[EvalToolFixture, ...] = ()
    appointment_probe: AppointmentProbe | None = None
    order_probe: OrderProbe | None = None

    @field_validator("fake_outputs")
    @classmethod
    def has_bounded_outputs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not output.strip() for output in value):
            raise ValueError("fake_outputs must contain non-empty text")
        return value

    @field_validator("tools")
    @classmethod
    def unique_tools(
        cls,
        value: tuple[EvalToolFixture, ...],
    ) -> tuple[EvalToolFixture, ...]:
        names = [tool.name for tool in value]
        if len(names) != len(set(names)):
            raise ValueError("fixture tool names must be unique")
        return value


class EvalExpected(StrictEvalModel):
    response_required: bool
    selected_tools: tuple[str, ...]
    persisted_result: bool
    credentials_absent: bool
    policy_classification: PolicyClassification | None = None
    response_language: ResponseLanguage | None = None
    truthful_disclosure: bool | None = None
    order_behavior: (
        Literal[
            "IDENTITY_REQUIRED",
            "CONFIRMATION_REQUIRED",
            "APPROVAL_REQUIRED",
            "READY",
            "UNAVAILABLE",
            "NEEDS_INFORMATION",
        ]
        | None
    ) = None
    appointment_behavior: (
        Literal[
            "IDENTITY_REQUIRED", "CONFIRMATION_REQUIRED", "APPROVAL_REQUIRED", "READY"
        ]
        | None
    ) = None

    @field_validator("selected_tools")
    @classmethod
    def canonical_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _TOOL_NAME.fullmatch(name) for name in value):
            raise ValueError("expected tool names must be capability-qualified")
        return tuple(sorted(set(value)))


class EvalCase(StrictEvalModel):
    schema_version: Literal[1]
    case_id: str
    input_turn: EvalInputTurn
    fixture_setup: EvalFixtureSetup
    expected: EvalExpected
    graders: tuple[GraderName, ...]
    tags: tuple[str, ...] = ()

    @field_validator("case_id")
    @classmethod
    def stable_case_id(cls, value: str) -> str:
        if not _CASE_ID.fullmatch(value):
            raise ValueError("case_id is invalid")
        return value

    @field_validator("graders")
    @classmethod
    def unique_graders(cls, value: tuple[GraderName, ...]) -> tuple[GraderName, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("graders must be non-empty and unique")
        return value

    @field_validator("tags")
    @classmethod
    def canonical_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))
