from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.modules.knowledge.embeddings import EmbeddingProvider
from agents_factory.modules.knowledge.repository import KnowledgeRepository
from agents_factory.modules.knowledge.retrieval import (
    KnowledgeQuery,
    KnowledgeRetriever,
)
from agents_factory.modules.knowledge.service import KnowledgeService
from agents_factory.modules.runtime.contracts import (
    AgentSpecSnapshot,
    RuntimeTool,
    ToolInvocationContext,
)


class KnowledgeToolModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KnowledgeRuntimeBinding(KnowledgeToolModel):
    tenant_id: UUID
    agent_spec_id: UUID
    agent_spec_digest: str = Field(pattern=r"[0-9a-f]{64}")
    knowledge_version_id: UUID
    knowledge_digest: str = Field(pattern=r"[0-9a-f]{64}")
    environment: Literal["TEST", "PRODUCTION"]


class BusinessDataLookupInput(KnowledgeToolModel):
    key: str = Field(pattern=r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")


class KnowledgeSearchInput(KnowledgeToolModel):
    query: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=5)


class KnowledgeRuntimeTools:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        embeddings: EmbeddingProvider,
    ) -> None:
        self._session_factory = session_factory
        self._embeddings = embeddings

    def for_agent(
        self,
        *,
        agent_spec: AgentSpecSnapshot,
        binding: KnowledgeRuntimeBinding,
        allow_test: bool = False,
    ) -> tuple[RuntimeTool, ...]:
        if (
            not agent_spec.active
            or binding.tenant_id != agent_spec.tenant_id
            or binding.agent_spec_id != agent_spec.id
            or binding.agent_spec_digest != agent_spec.digest
            or (binding.environment != "PRODUCTION" and not allow_test)
        ):
            return ()

        async def business_data_lookup(
            context: ToolInvocationContext,
            arguments: Mapping[str, object],
        ) -> object:
            payload = BusinessDataLookupInput.model_validate(arguments)
            self._require_tenant(context, binding)
            tenant_context = _tenant_context(context)
            async with self._session_factory.begin() as session:
                await session.execute(text("SET LOCAL ROLE agents_factory_app"))
                if not await _binding_is_exact(session, binding):
                    return _unknown(payload.key, "knowledge_binding_unavailable")
                resolution = await KnowledgeService(
                    KnowledgeRepository(session, tenant_context)
                ).resolve_fact(
                    version_id=binding.knowledge_version_id,
                    key=payload.key,
                )
                if resolution.selected is None or resolution.has_conflict:
                    reason = (
                        "authoritative_conflict"
                        if resolution.has_conflict
                        else "approved_fact_unavailable"
                    )
                    return _unknown(payload.key, reason)
                selected = resolution.selected
                locator = await session.scalar(
                    text(
                        "SELECT locator FROM public.knowledge_source_versions "
                        "WHERE tenant_id = :tenant_id AND id = :source_version_id"
                    ),
                    {
                        "tenant_id": binding.tenant_id,
                        "source_version_id": selected.provenance.source_version_id,
                    },
                )
            return {
                "status": "FOUND",
                "key": selected.key,
                "value": selected.value,
                "provenance": {
                    "source_id": str(selected.provenance.source_id),
                    "source_version_id": str(selected.provenance.source_version_id),
                    "authority": selected.provenance.authority,
                    "content_digest": selected.provenance.content_digest,
                    "locator": locator or {},
                },
            }

        async def knowledge_search(
            context: ToolInvocationContext,
            arguments: Mapping[str, object],
        ) -> object:
            payload = KnowledgeSearchInput.model_validate(arguments)
            self._require_tenant(context, binding)
            async with self._session_factory.begin() as session:
                await session.execute(text("SET LOCAL ROLE agents_factory_app"))
                if not await _binding_is_exact(session, binding):
                    return {
                        "status": "UNKNOWN",
                        "reason": "knowledge_binding_unavailable",
                        "snippets": [],
                    }
                hits = await KnowledgeRetriever(
                    session=session,
                    context=_tenant_context(context),
                    embeddings=self._embeddings,
                ).retrieve(
                    KnowledgeQuery(
                        knowledge_version_id=binding.knowledge_version_id,
                        knowledge_digest=binding.knowledge_digest,
                        text=payload.query,
                        top_k=payload.top_k,
                    )
                )
            return {
                "status": "FOUND" if hits else "UNKNOWN",
                "snippets": [
                    {
                        "text": hit.text[:1_200],
                        "score": round(hit.score, 6),
                        "source_id": str(hit.source_id),
                        "source_version_id": str(hit.source_version_id),
                        "authority": hit.authority,
                        "locator": hit.locator,
                        "content_digest": hit.content_digest,
                    }
                    for hit in hits
                ],
            }

        return (
            RuntimeTool(
                name="business_data.lookup",
                capability="business_data",
                description=(
                    "Look up one approved structured business fact from the exact "
                    "active Knowledge version."
                ),
                input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
                handler=business_data_lookup,
            ),
            RuntimeTool(
                name="knowledge.search",
                capability="knowledge",
                description=(
                    "Search approved policy and manual snippets with source provenance."
                ),
                input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string", "maxLength": 2_000},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                    "required": ["query"],
                },
                handler=knowledge_search,
            ),
        )

    @staticmethod
    def _require_tenant(
        invocation: ToolInvocationContext,
        binding: KnowledgeRuntimeBinding,
    ) -> None:
        if invocation.tenant_id != binding.tenant_id:
            raise PermissionError("Knowledge tool tenant binding mismatch")


async def _binding_is_exact(
    session: AsyncSession,
    binding: KnowledgeRuntimeBinding,
) -> bool:
    state = cast(
        str | None,
        await session.scalar(
            text(
                "SELECT state FROM public.knowledge_versions "
                "WHERE tenant_id = :tenant_id AND id = :version_id "
                "AND digest = :digest AND state = :environment"
            ),
            {
                "tenant_id": binding.tenant_id,
                "version_id": binding.knowledge_version_id,
                "digest": binding.knowledge_digest,
                "environment": binding.environment,
            },
        ),
    )
    return state == binding.environment


def _tenant_context(invocation: ToolInvocationContext) -> TenantContext:
    return TenantContext(
        tenant_id=invocation.tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=invocation.correlation_id,
    )


def _unknown(key: str, reason: str) -> dict[str, object]:
    return {
        "status": "UNKNOWN",
        "key": key,
        "reason": reason,
        "requires_human": True,
    }
