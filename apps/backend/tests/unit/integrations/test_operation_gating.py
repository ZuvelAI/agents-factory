from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import pytest

from agents_factory.modules.agent_factory.models import (
    AgentSpec,
    AgentSpecConfiguration,
    ConnectorBinding,
    HumanOperationsConfiguration,
    PersonaConfiguration,
    VersionedDigestReference,
    VersionReference,
)
from agents_factory.modules.capabilities.contracts import (
    ActionDefinition,
    CapabilityManifest,
    RiskLevel,
)
from agents_factory.modules.capabilities.registry import CapabilityRegistry
from agents_factory.modules.capabilities.service import (
    AgentSpecManifestError,
    CapabilityService,
)
from agents_factory.modules.integrations.contracts import ConnectorManifest
from agents_factory.modules.integrations.registry import (
    ConnectorRegistry,
    V1_CONNECTOR_CATALOG,
)
from agents_factory.modules.runtime.contracts import RuntimeTool, ToolInvocationContext


ROOT = Path(__file__).resolve().parents[5]
BINDING_ID = UUID("40000000-0000-0000-0000-000000000013")


async def handler(
    context: ToolInvocationContext, arguments: Mapping[str, object]
) -> object:
    _ = (context, arguments)
    return {}


def action(name: str, risk: RiskLevel) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        description=name,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        risk=risk,
        required_identity_level=1,
        requires_confirmation=name.endswith("cancel"),
        requires_approval=name.endswith("cancel"),
        failure_behavior="Do not claim success.",
        handoff_behavior="Offer human help.",
        eval_case_ids=(f"{name}.case",),
    )


def orders_capability() -> CapabilityManifest:
    return CapabilityManifest(
        stable_name="orders",
        version="1.0.0",
        intents=("order_status", "order_cancel"),
        workflow=("identify", "execute", "respond"),
        business_schemas={"order": {"type": "object"}},
        actions=(
            action("orders.get_status", "LOW"),
            action("orders.cancel", "HIGH"),
        ),
    )


def connector(*, operations: tuple[str, ...]) -> ConnectorManifest:
    return ConnectorManifest(
        stable_name="woocommerce",
        display_name="WooCommerce",
        version="1.0.0",
        availability="AVAILABLE",
        supported_operations=operations,
        availability_note="Available when connected.",
        executable_entry_point="agents_factory.integrations.woocommerce",
    )


def spec(*, bound_operations: tuple[str, ...]) -> AgentSpec:
    return AgentSpec(
        tenant_id=UUID("10000000-0000-0000-0000-000000000013"),
        agent_instance_id=UUID("20000000-0000-0000-0000-000000000013"),
        version_id=UUID("30000000-0000-0000-0000-000000000013"),
        version_number=1,
        configuration=AgentSpecConfiguration(
            product_version="1.0.0",
            persona=PersonaConfiguration(version="1", instructions="Help."),
            capabilities=(VersionReference(name="orders", version="1.0.0"),),
            permitted_tools=("orders.get_status",),
            permitted_actions=("orders.cancel",),
            connector_bindings=(
                ConnectorBinding(
                    binding_id=BINDING_ID,
                    connector="woocommerce",
                    connector_version="1.0.0",
                    operations=bound_operations,
                ),
            ),
            policy=VersionReference(name="customer_service", version="1"),
            identity_policy=VersionReference(name="standard", version="1"),
            approval_routes=VersionReference(name="standard", version="1"),
            knowledge=VersionedDigestReference(
                name="knowledge", version="1", digest="a" * 64
            ),
            human_operations=HumanOperationsConfiguration(version="1"),
            code_digest="b" * 64,
        ),
    )


def tools() -> tuple[RuntimeTool, ...]:
    return (
        RuntimeTool(
            name="orders.get_status",
            capability="orders",
            description="Read status.",
            input_schema={"type": "object"},
            handler=handler,
        ),
        RuntimeTool(
            name="orders.cancel",
            capability="orders",
            description="Cancel order.",
            input_schema={"type": "object"},
            handler=handler,
        ),
    )


def test_only_active_permitted_and_connector_supported_tools_are_offered() -> None:
    service = CapabilityService(
        capabilities=CapabilityRegistry((orders_capability(),)),
        connectors=ConnectorRegistry(
            (connector(operations=("orders.get_status", "orders.cancel")),)
        ),
    )
    selected = service.select_tools(
        spec=spec(bound_operations=("orders.get_status", "orders.cancel")),
        relevant_capabilities=frozenset({"orders"}),
        tools=tools(),
    )

    assert tuple(tool.name for tool in selected) == ("orders.get_status",)


def test_unsupported_bound_operations_fail_closed() -> None:
    service = CapabilityService(
        capabilities=CapabilityRegistry((orders_capability(),)),
        connectors=ConnectorRegistry((connector(operations=("orders.get_status",)),)),
    )

    with pytest.raises(AgentSpecManifestError, match="unsupported operations"):
        service.validate_agent_spec(
            spec(bound_operations=("orders.get_status", "orders.cancel"))
        )


def test_planned_connectors_are_metadata_only_and_schema_is_generated() -> None:
    planned = V1_CONNECTOR_CATALOG.list()
    schema_path = ROOT / "packages/integrations/connector.schema.json"

    assert planned
    assert all(item.availability == "UNAVAILABLE" for item in planned)
    assert all(item.supported_operations == () for item in planned)
    assert all(item.executable_entry_point is None for item in planned)
    assert json.loads(schema_path.read_text(encoding="utf-8")) == (
        ConnectorManifest.model_json_schema()
    )
