from __future__ import annotations

from collections.abc import Iterable

from agents_factory.modules.runtime.contracts import (
    AgentSpecSnapshot,
    RuntimeTool,
)


class DuplicateRuntimeTool(ValueError):
    pass


class RuntimeToolRegistry:
    def __init__(self, tools: Iterable[RuntimeTool]) -> None:
        indexed: dict[str, RuntimeTool] = {}
        for tool in tools:
            if tool.name in indexed:
                raise DuplicateRuntimeTool(tool.name)
            indexed[tool.name] = tool
        self._tools = indexed

    def with_tools(self, tools: Iterable[RuntimeTool]) -> RuntimeToolRegistry:
        """Return a new registry with request-scoped, pre-authorized tools."""
        return RuntimeToolRegistry((*self._tools.values(), *tools))

    def select(
        self,
        *,
        agent_spec: AgentSpecSnapshot,
        relevant_capabilities: frozenset[str],
    ) -> tuple[RuntimeTool, ...]:
        if not agent_spec.active:
            return ()
        relevant_and_active = relevant_capabilities & agent_spec.active_capabilities
        return tuple(
            tool
            for name, tool in sorted(self._tools.items())
            if tool.active
            and tool.capability in relevant_and_active
            and name in agent_spec.permitted_tools
        )
