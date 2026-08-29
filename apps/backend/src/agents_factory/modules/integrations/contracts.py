from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


ConnectorAvailability = Literal["AVAILABLE", "UNAVAILABLE"]
ConnectorResultStatus = Literal["SUCCEEDED", "REJECTED", "FAILED", "UNCERTAIN"]
_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?"
)
_STABLE_NAME = re.compile(r"[a-z][a-z0-9_]*")
_OPERATION = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")


class FrozenConnectorModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ConnectorManifest(FrozenConnectorModel):
    stable_name: str = Field(pattern=_STABLE_NAME.pattern)
    display_name: str = Field(min_length=1, max_length=200)
    version: str = Field(pattern=_SEMVER.pattern)
    availability: ConnectorAvailability
    supported_operations: tuple[str, ...] = ()
    availability_note: str = Field(min_length=1, max_length=500)
    executable_entry_point: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_availability(self) -> Self:
        if len(set(self.supported_operations)) != len(self.supported_operations):
            raise ValueError("connector operations must be unique")
        if any(
            not _OPERATION.fullmatch(operation)
            for operation in self.supported_operations
        ):
            raise ValueError("connector operations must be business-qualified")
        if self.availability == "UNAVAILABLE" and (
            self.supported_operations or self.executable_entry_point is not None
        ):
            raise ValueError("unavailable connectors cannot be executable")
        if self.availability == "AVAILABLE" and self.executable_entry_point is None:
            raise ValueError("available connectors require a registered entry point")
        return self


class ConnectorRequest(FrozenConnectorModel):
    tenant_id: UUID
    binding_id: UUID
    operation: str = Field(pattern=_OPERATION.pattern)
    arguments: dict[str, object]
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=300)


class ConnectorResult(FrozenConnectorModel):
    operation: str = Field(pattern=_OPERATION.pattern)
    status: ConnectorResultStatus
    data: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, min_length=1, max_length=120)


class Connector(Protocol):
    async def execute(self, request: ConnectorRequest) -> ConnectorResult: ...


class ConnectorExecutor(Protocol):
    async def __call__(
        self, *, operation: str, arguments: Mapping[str, object]
    ) -> Mapping[str, object]: ...
