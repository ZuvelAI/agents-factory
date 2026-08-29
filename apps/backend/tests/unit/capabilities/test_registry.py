from __future__ import annotations

import pytest

from agents_factory.modules.capabilities.contracts import (
    ActionDefinition,
    CapabilityManifest,
    TenantExtensionManifest,
)
from agents_factory.modules.capabilities.registry import (
    CapabilityRegistry,
    DuplicateManifest,
    ExtensionRegistrationError,
    TenantExtensionRegistry,
    V1_TENANT_EXTENSIONS,
)


def action(name: str = "orders.get_status") -> ActionDefinition:
    return ActionDefinition(
        name=name,
        description="Read the current order status.",
        input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        risk="LOW",
        required_identity_level=1,
        requires_confirmation=False,
        requires_approval=False,
        failure_behavior="Report that status is unavailable without guessing.",
        handoff_behavior="Offer human handoff after a bounded connector failure.",
        eval_case_ids=("orders.status.happy_path",),
    )


def manifest() -> CapabilityManifest:
    return CapabilityManifest(
        stable_name="orders",
        version="1.0.0",
        intents=("order_status",),
        workflow=("identify_order", "read_status", "respond"),
        business_schemas={"order": {"type": "object"}},
        actions=(action(),),
    )


def test_registry_is_version_keyed_and_manifest_contains_safety_metadata() -> None:
    registry = CapabilityRegistry((manifest(),))

    registered = registry.get("orders", "1.0.0")

    assert registered.actions[0].risk == "LOW"
    assert registered.actions[0].required_identity_level == 1
    assert registered.actions[0].failure_behavior
    assert registered.actions[0].handoff_behavior
    assert registered.actions[0].eval_case_ids
    with pytest.raises(DuplicateManifest):
        registry.register(manifest())


def test_tenant_extensions_require_registered_entry_points_and_ship_empty() -> None:
    extension = TenantExtensionManifest(
        stable_name="customer_workflow",
        version="1.0.0",
        owner="ZuvelAI",
        platform_compatibility=">=1.0.0,<2.0.0",
        isolated_tests=("extensions/customer_workflow/test_contract.py",),
        deployment_artifact="oci://registry/customer-workflow:1.0.0",
        rollback_target="oci://registry/customer-workflow:0.9.0",
        entry_point="agents_factory.extensions.customer_workflow",
    )
    registry = TenantExtensionRegistry(registered_entry_points=(extension.entry_point,))
    registry.register(extension)

    assert registry.list() == (extension,)
    assert extension.enabled is False
    assert V1_TENANT_EXTENSIONS.list() == ()

    with pytest.raises(ExtensionRegistrationError):
        TenantExtensionRegistry().register(extension)
    with pytest.raises(ExtensionRegistrationError):
        registry.register(extension.model_copy(update={"enabled": True}))
