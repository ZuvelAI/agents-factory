from __future__ import annotations

from uuid import UUID

from agents_factory.modules.agent_factory.models import (
    AgentSpec,
    AgentSpecConfiguration,
    HumanOperationsConfiguration,
    PersonaConfiguration,
    VersionedDigestReference,
    VersionReference,
)
from agents_factory.modules.runtime.customer_service.instructions import (
    CustomerServiceInstructionsBuilder,
)
from agents_factory.modules.runtime.customer_service.quick_options import (
    build_quick_options,
)


def spec(*, handoff_enabled: bool = True) -> AgentSpec:
    return AgentSpec(
        tenant_id=UUID("10000000-0000-0000-0000-000000000016"),
        agent_instance_id=UUID("20000000-0000-0000-0000-000000000016"),
        version_id=UUID("30000000-0000-0000-0000-000000000016"),
        version_number=1,
        configuration=AgentSpecConfiguration(
            product_version="1.0.0",
            persona=PersonaConfiguration(
                version="1",
                business_name="Zuvel Store",
                instructions="Usa un tono cálido y llama al negocio Zuvel Store.",
            ),
            capabilities=(
                VersionReference(name="orders", version="1.0.0"),
                VersionReference(name="appointments", version="1.0.0"),
            ),
            policy=VersionReference(name="customer_service", version="1"),
            identity_policy=VersionReference(name="standard", version="1"),
            approval_routes=VersionReference(name="standard", version="1"),
            knowledge=VersionedDigestReference(
                name="knowledge", version="1", digest="a" * 64
            ),
            human_operations=HumanOperationsConfiguration(
                version="1", handoff_enabled=handoff_enabled
            ),
            code_digest="b" * 64,
        ),
    )


def test_quick_options_come_only_from_active_capabilities() -> None:
    options = build_quick_options(
        active_capabilities=frozenset({"orders", "appointments", "unknown"}),
        language="es",
        handoff_enabled=False,
        handoff_surface_available=False,
    )

    assert options == ("Gestionar una cita", "Consultar un pedido")


def test_human_option_requires_enabled_and_valid_surface() -> None:
    without_surface = build_quick_options(
        active_capabilities=frozenset({"orders"}),
        language="es",
        handoff_enabled=True,
        handoff_surface_available=False,
    )
    with_surface = build_quick_options(
        active_capabilities=frozenset({"orders"}),
        language="es",
        handoff_enabled=True,
        handoff_surface_available=True,
    )

    assert "Hablar con una persona" not in without_surface
    assert with_surface[-1] == "Hablar con una persona"


def test_instruction_builder_includes_brand_capabilities_and_safe_handoff() -> None:
    instructions = CustomerServiceInstructionsBuilder().build(
        spec=spec(),
        handoff_surface_available=False,
    )

    assert "Business: Zuvel Store" in instructions
    assert "Gestionar una cita" in instructions
    assert "Consultar un pedido" in instructions
    assert "Hablar con una persona" not in instructions
