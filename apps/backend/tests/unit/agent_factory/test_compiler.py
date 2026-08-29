from __future__ import annotations

from uuid import UUID

import pytest

from agents_factory.modules.agent_factory.compiler import AgentSpecCompiler
from agents_factory.modules.agent_factory.models import (
    AgentSpecConfiguration,
    AgentSpecDraft,
    ConnectorBinding,
    HumanOperationsConfiguration,
    PersonaConfiguration,
    VersionedDigestReference,
    VersionReference,
)


TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
INSTANCE_ID = UUID("20000000-0000-0000-0000-000000000001")
VERSION_ID = UUID("30000000-0000-0000-0000-000000000001")
BINDING_ID = UUID("40000000-0000-0000-0000-000000000001")
DIGEST = "a" * 64


class Drafts:
    def __init__(self, draft: AgentSpecDraft) -> None:
        self.draft = draft

    async def get_draft(
        self, *, agent_instance_id: UUID, draft_version_id: UUID
    ) -> AgentSpecDraft | None:
        if (agent_instance_id, draft_version_id) != (INSTANCE_ID, VERSION_ID):
            return None
        return self.draft


def configuration(*, reverse: bool = False) -> AgentSpecConfiguration:
    capabilities = (
        VersionReference(name="orders", version="1.0.0"),
        VersionReference(name="appointments", version="1.0.0"),
    )
    tools = ("orders.get_status", "appointments.get_availability")
    return AgentSpecConfiguration(
        product_version="1.0.0",
        persona=PersonaConfiguration(version="1", instructions="Ayuda con claridad."),
        capabilities=tuple(reversed(capabilities)) if reverse else capabilities,
        permitted_tools=tuple(reversed(tools)) if reverse else tools,
        permitted_actions=("orders.cancel",),
        connector_bindings=(
            ConnectorBinding(
                binding_id=BINDING_ID,
                connector="woocommerce",
                connector_version="1.0.0",
                operations=("orders.get_status", "orders.cancel"),
            ),
        ),
        policy=VersionReference(name="customer_service", version="1"),
        identity_policy=VersionReference(name="standard", version="1"),
        approval_routes=VersionReference(name="standard", version="1"),
        knowledge=VersionedDigestReference(
            name="tenant_knowledge", version="1", digest=DIGEST
        ),
        human_operations=HumanOperationsConfiguration(version="1"),
        code_digest="b" * 64,
    )


@pytest.mark.asyncio
async def test_compiler_emits_complete_deterministic_agent_spec() -> None:
    first = await AgentSpecCompiler(
        Drafts(
            AgentSpecDraft(
                id=VERSION_ID,
                tenant_id=TENANT_ID,
                agent_instance_id=INSTANCE_ID,
                version_number=2,
                configuration=configuration(),
            )
        )
    ).compile(INSTANCE_ID, VERSION_ID)
    reordered = await AgentSpecCompiler(
        Drafts(
            AgentSpecDraft(
                id=VERSION_ID,
                tenant_id=TENANT_ID,
                agent_instance_id=INSTANCE_ID,
                version_number=2,
                configuration=configuration(reverse=True),
            )
        )
    ).compile(INSTANCE_ID, VERSION_ID)

    assert first.canonical_json == reordered.canonical_json
    assert first.digest == reordered.digest
    assert first.spec.product == "Agent Customer Service"
    assert first.spec.configuration.model.model == "gpt-5.6-luna"
    assert first.spec.configuration.model.reasoning_effort == "low"
    assert first.spec.configuration.language.default_locale == "es-CO"
    assert first.spec.configuration.language.supported_locales == ("es-CO", "en-US")
    assert first.spec.configuration.knowledge.digest == DIGEST
    assert first.spec.configuration.human_operations.version == "1"


@pytest.mark.asyncio
async def test_compiled_spec_projects_explicitly_to_runtime_snapshot() -> None:
    compiled = await AgentSpecCompiler(
        Drafts(
            AgentSpecDraft(
                id=VERSION_ID,
                tenant_id=TENANT_ID,
                agent_instance_id=INSTANCE_ID,
                version_number=1,
                configuration=configuration(),
            )
        )
    ).compile(INSTANCE_ID, VERSION_ID)

    snapshot = compiled.spec.to_runtime_snapshot(active=False)

    assert snapshot.id == VERSION_ID
    assert snapshot.digest == compiled.digest
    assert snapshot.active is False
    assert snapshot.product == "Agent Customer Service"
