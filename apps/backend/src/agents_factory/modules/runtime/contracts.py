from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID


TurnRole = Literal["user", "assistant"]
ReasoningEffort = Literal["low"]
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_TOOL_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_SENSITIVE_FIELD_FRAGMENTS = (
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "password",
    "refresh_token",
    "secret",
)


@dataclass(frozen=True, slots=True)
class ModelConfiguration:
    model: str = "gpt-5.6-luna"
    reasoning_effort: ReasoningEffort = "low"

    def __post_init__(self) -> None:
        if self.model != "gpt-5.6-luna" or self.reasoning_effort != "low":
            raise ValueError("v1 runtime model configuration is fixed")


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    max_output_tokens: int = 2_048
    max_tool_calls: int = 8
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_output_tokens <= 16_384:
            raise ValueError("max_output_tokens is outside the technical boundary")
        if not 0 <= self.max_tool_calls <= 32:
            raise ValueError("max_tool_calls is outside the technical boundary")
        if not 0 < self.timeout_seconds <= 300:
            raise ValueError("timeout_seconds is outside the technical boundary")


@dataclass(frozen=True, slots=True)
class AgentSpecSnapshot:
    """Immutable runtime view; Task 12 will compile and persist the full AgentSpec."""

    id: UUID
    tenant_id: UUID
    version: str
    digest: str
    product: str
    product_version: str
    instructions: str
    active_capabilities: frozenset[str]
    permitted_tools: frozenset[str]
    model: ModelConfiguration
    limits: RuntimeLimits
    active: bool

    def __post_init__(self) -> None:
        bounded_values = (
            self.version,
            self.product,
            self.product_version,
            self.instructions,
        )
        if any(not value.strip() for value in bounded_values):
            raise ValueError("AgentSpec runtime fields must be non-empty")
        if not _DIGEST_PATTERN.fullmatch(self.digest):
            raise ValueError("AgentSpec digest must be lowercase SHA-256")
        if not self.permitted_tools.issubset(
            {
                name
                for name in self.permitted_tools
                if _TOOL_NAME_PATTERN.fullmatch(name)
            }
        ):
            raise ValueError("AgentSpec contains an invalid tool name")


@dataclass(frozen=True, slots=True)
class TurnMessage:
    id: UUID
    role: TurnRole
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("runtime messages must contain text")


@dataclass(frozen=True, slots=True)
class RuntimeTraceMetadata:
    tenant_id: UUID
    conversation_id: UUID
    inbound_message_id: UUID
    correlation_id: UUID
    agent_spec_id: UUID
    agent_spec_digest: str

    def as_sdk_metadata(self) -> dict[str, str]:
        return {
            "tenant_id": str(self.tenant_id),
            "conversation_id": str(self.conversation_id),
            "inbound_message_id": str(self.inbound_message_id),
            "correlation_id": str(self.correlation_id),
            "agent_spec_id": str(self.agent_spec_id),
            "agent_spec_digest": self.agent_spec_digest,
        }


@dataclass(frozen=True, slots=True)
class ToolInvocationContext:
    tenant_id: UUID
    conversation_id: UUID
    inbound_message_id: UUID
    correlation_id: UUID


class RuntimeToolHandler(Protocol):
    async def __call__(
        self,
        context: ToolInvocationContext,
        arguments: Mapping[str, object],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class RuntimeTool:
    name: str
    capability: str
    description: str
    input_schema: Mapping[str, object]
    handler: RuntimeToolHandler = field(repr=False, compare=False)
    active: bool = True

    def __post_init__(self) -> None:
        if not _TOOL_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("runtime tool names must be capability-qualified")
        if not self.capability.strip() or not self.description.strip():
            raise ValueError("runtime tool metadata must be non-empty")
        if self.name.partition(".")[0] != self.capability:
            raise ValueError("runtime tool capability does not match its name")
        _reject_sensitive_fields(self.input_schema)


@dataclass(frozen=True, slots=True)
class AgentTurnInput:
    agent_spec: AgentSpecSnapshot
    messages: tuple[TurnMessage, ...]
    tools: tuple[RuntimeTool, ...]
    trace: RuntimeTraceMetadata
    execution: RuntimeExecutionPolicy | None = None
    observer: RuntimeObserver | None = field(default=None, repr=False, compare=False)
    admission: RuntimeAdmission | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.messages or self.messages[-1].role != "user":
            raise ValueError("an agent turn must end with a customer message")
        if self.agent_spec.tenant_id != self.trace.tenant_id:
            raise ValueError("AgentSpec tenant does not match the turn")
        if self.agent_spec.id != self.trace.agent_spec_id:
            raise ValueError("AgentSpec identity does not match the trace")
        if self.agent_spec.digest != self.trace.agent_spec_digest:
            raise ValueError("AgentSpec digest does not match the trace")


@dataclass(frozen=True, slots=True)
class RuntimeToolCall:
    tool_name: str
    arguments: Mapping[str, object]
    output: object


@dataclass(frozen=True, slots=True)
class RuntimeUsage:
    requests: int | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True, slots=True)
class RuntimeExecutionPolicy:
    max_tool_calls: int
    max_model_tokens: int

    def __post_init__(self) -> None:
        if not 0 <= self.max_tool_calls <= 32 or self.max_model_tokens < 1:
            raise ValueError("invalid runtime execution policy")


class RuntimeObserver(Protocol):
    async def model_response(self, usage: RuntimeUsage, latency_ms: int) -> None: ...

    async def tool_attempt(self, name: str, latency_ms: int) -> None: ...


class RuntimeAdmission(Protocol):
    async def before_model(self) -> None: ...

    async def before_tool(self) -> None: ...


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    output_text: str
    tool_calls: tuple[RuntimeToolCall, ...]
    usage: RuntimeUsage
    provider_response_id: str | None

    def __post_init__(self) -> None:
        if not self.output_text.strip():
            raise ValueError("runtime output must contain customer-visible text")


class AgentRuntime(Protocol):
    async def run(self, turn: AgentTurnInput) -> AgentTurnResult: ...


def reject_sensitive_fields(value: object) -> None:
    _reject_sensitive_fields(value)


def _reject_sensitive_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(fragment in normalized for fragment in _SENSITIVE_FIELD_FRAGMENTS):
                raise ValueError("runtime contract contains a credential-like field")
            _reject_sensitive_fields(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_sensitive_fields(nested)
