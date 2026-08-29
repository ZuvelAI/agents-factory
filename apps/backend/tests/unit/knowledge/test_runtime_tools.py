from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal, cast
from uuid import uuid4

from agents_factory.modules.knowledge.embeddings import DeterministicEmbeddingProvider
from agents_factory.modules.knowledge.tools import (
    KnowledgeRuntimeBinding,
    KnowledgeRuntimeTools,
)
from agents_factory.modules.runtime.contracts import (
    AgentSpecSnapshot,
    ModelConfiguration,
    RuntimeLimits,
)
from agents_factory.modules.runtime.tool_registry import RuntimeToolRegistry


def _spec() -> AgentSpecSnapshot:
    return AgentSpecSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        version="1",
        digest="a" * 64,
        product="customer_service",
        product_version="1.0.0",
        instructions="Use only approved Knowledge tools.",
        active_capabilities=frozenset({"business_data", "knowledge"}),
        permitted_tools=frozenset({"business_data.lookup", "knowledge.search"}),
        model=ModelConfiguration(),
        limits=RuntimeLimits(),
        active=True,
    )


def _binding(
    spec: AgentSpecSnapshot,
    environment: Literal["TEST", "PRODUCTION"],
) -> KnowledgeRuntimeBinding:
    return KnowledgeRuntimeBinding(
        tenant_id=spec.tenant_id,
        agent_spec_id=spec.id,
        agent_spec_digest=spec.digest,
        knowledge_version_id=uuid4(),
        knowledge_digest="b" * 64,
        environment=environment,
    )


def test_structured_and_rag_tools_are_selected_separately() -> None:
    spec = _spec()
    factory = KnowledgeRuntimeTools(
        session_factory=cast(Any, object()),
        embeddings=DeterministicEmbeddingProvider(),
    )
    registry = RuntimeToolRegistry(()).with_tools(
        factory.for_agent(
            agent_spec=spec,
            binding=_binding(spec, "PRODUCTION"),
        )
    )

    structured = registry.select(
        agent_spec=spec,
        relevant_capabilities=frozenset({"business_data"}),
    )
    rag = registry.select(
        agent_spec=spec,
        relevant_capabilities=frozenset({"knowledge"}),
    )

    assert tuple(tool.name for tool in structured) == ("business_data.lookup",)
    assert tuple(tool.name for tool in rag) == ("knowledge.search",)


def test_tools_are_omitted_without_an_exact_deployable_binding() -> None:
    spec = _spec()
    factory = KnowledgeRuntimeTools(
        session_factory=cast(Any, object()),
        embeddings=DeterministicEmbeddingProvider(),
    )
    test_binding = _binding(spec, "TEST")
    wrong_spec = replace(spec, digest="c" * 64)

    assert factory.for_agent(agent_spec=spec, binding=test_binding) == ()
    assert factory.for_agent(
        agent_spec=spec,
        binding=test_binding,
        allow_test=True,
    )
    assert (
        factory.for_agent(
            agent_spec=wrong_spec,
            binding=test_binding,
            allow_test=True,
        )
        == ()
    )
