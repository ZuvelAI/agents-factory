from __future__ import annotations

from collections.abc import Iterable

from agents_factory.modules.agent_factory.models import AgentSpec
from agents_factory.modules.capabilities.registry import (
    CapabilityRegistry,
    ManifestNotFound,
)
from agents_factory.modules.integrations.registry import (
    ConnectorManifestNotFound,
    ConnectorRegistry,
)
from agents_factory.modules.runtime.contracts import RuntimeTool
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry


class AgentSpecManifestError(ValueError):
    pass


class CapabilityService:
    def __init__(
        self,
        *,
        capabilities: CapabilityRegistry,
        connectors: ConnectorRegistry,
    ) -> None:
        self._capabilities = capabilities
        self._connectors = connectors

    def validate_agent_spec(self, spec: AgentSpec) -> None:
        actions: set[str] = set()
        try:
            for reference in spec.configuration.capabilities:
                manifest = self._capabilities.get(reference.name, reference.version)
                actions.update(action.name for action in manifest.actions)
            available_operations = self._available_binding_operations(spec)
        except (ManifestNotFound, ConnectorManifestNotFound) as error:
            raise AgentSpecManifestError(str(error)) from error

        permitted = set(spec.configuration.permitted_tools) | set(
            spec.configuration.permitted_actions
        )
        unknown = permitted - actions
        if unknown:
            raise AgentSpecManifestError(
                f"AgentSpec operations are not declared by active capabilities: "
                f"{sorted(unknown)}"
            )
        unsupported = permitted - available_operations
        if unsupported:
            raise AgentSpecManifestError(
                f"AgentSpec operations are not supported by bound connectors: "
                f"{sorted(unsupported)}"
            )

    def select_tools(
        self,
        *,
        spec: AgentSpec,
        relevant_capabilities: frozenset[str],
        tools: Iterable[RuntimeTool],
    ) -> tuple[RuntimeTool, ...]:
        self.validate_agent_spec(spec)
        candidates = RuntimeToolRegistry(tools).select(
            agent_spec=spec.to_runtime_snapshot(active=True),
            relevant_capabilities=relevant_capabilities,
        )
        available_operations = self._available_binding_operations(spec)
        return tuple(tool for tool in candidates if tool.name in available_operations)

    def _available_binding_operations(self, spec: AgentSpec) -> set[str]:
        operations: set[str] = set()
        for binding in spec.configuration.connector_bindings:
            manifest = self._connectors.get(
                binding.connector,
                binding.connector_version,
            )
            declared = set(manifest.supported_operations)
            bound = set(binding.operations)
            if manifest.availability != "AVAILABLE":
                if bound:
                    raise AgentSpecManifestError(
                        f"connector {manifest.stable_name} is unavailable"
                    )
                continue
            if not bound.issubset(declared):
                raise AgentSpecManifestError(
                    f"binding requests unsupported operations: "
                    f"{sorted(bound - declared)}"
                )
            operations.update(bound)
        return operations
