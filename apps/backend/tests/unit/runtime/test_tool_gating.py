from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from agents_factory.modules.runtime.contracts import (
    AgentSpecSnapshot,
    ModelConfiguration,
    RuntimeLimits,
    RuntimeTool,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry


async def _tool_handler(
    _context: object,
    _arguments: object,
) -> dict[str, object]:
    return {"ok": True}


def _agent_spec() -> AgentSpecSnapshot:
    return AgentSpecSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        version="test-v1",
        digest="a" * 64,
        product="customer_service",
        product_version="1.0.0",
        instructions="Serve the customer using only the supplied tools.",
        active_capabilities=frozenset({"appointments", "orders"}),
        permitted_tools=frozenset({"appointments.find_slots", "orders.get_status"}),
        model=ModelConfiguration(),
        limits=RuntimeLimits(
            max_output_tokens=512,
            max_tool_calls=3,
            timeout_seconds=10.0,
        ),
        active=True,
    )


def test_registry_exposes_only_active_relevant_permitted_tools() -> None:
    registry = RuntimeToolRegistry(
        (
            RuntimeTool(
                name="orders.cancel",
                capability="orders",
                description="Cancel an eligible order.",
                input_schema={"type": "object", "properties": {}},
                handler=_tool_handler,
            ),
            RuntimeTool(
                name="appointments.find_slots",
                capability="appointments",
                description="Find available appointment slots.",
                input_schema={"type": "object", "properties": {}},
                handler=_tool_handler,
            ),
            RuntimeTool(
                name="orders.get_status",
                capability="orders",
                description="Read an order status.",
                input_schema={"type": "object", "properties": {}},
                handler=_tool_handler,
                active=False,
            ),
        )
    )

    selected = registry.select(
        agent_spec=_agent_spec(),
        relevant_capabilities=frozenset({"appointments"}),
    )

    assert tuple(tool.name for tool in selected) == ("appointments.find_slots",)


def test_runtime_contract_is_immutable_and_rejects_credential_fields() -> None:
    spec = _agent_spec()
    with pytest.raises(FrozenInstanceError):
        spec.version = "changed"  # type: ignore[misc]

    with pytest.raises(ValueError, match="credential-like"):
        RuntimeTool(
            name="orders.lookup",
            capability="orders",
            description="Unsafe test tool.",
            input_schema={
                "type": "object",
                "properties": {"refresh_token": {"type": "string"}},
            },
            handler=_tool_handler,
        )
