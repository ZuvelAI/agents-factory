from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.knowledge.embeddings import (
    EmbeddingProvider,
    embedding_literal,
)
from agents_factory.modules.knowledge.models import KnowledgeAuthority


class RetrievalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KnowledgeQuery(RetrievalModel):
    knowledge_version_id: UUID
    knowledge_digest: str = Field(pattern=r"[0-9a-f]{64}")
    text: str = Field(min_length=1, max_length=4_000)
    top_k: int = Field(default=5, ge=1, le=10)
    minimum_score: float = Field(default=0.15, ge=-1.0, le=1.0)
    timeout_ms: int = Field(default=1_500, ge=50, le=2_000)


class KnowledgeHit(RetrievalModel):
    chunk_id: UUID
    text: str
    score: float
    source_id: UUID
    source_version_id: UUID
    authority: KnowledgeAuthority
    locator: dict[str, object]
    document_id: UUID
    content_digest: str = Field(pattern=r"[0-9a-f]{64}")


class KnowledgeRetriever:
    def __init__(
        self,
        *,
        session: AsyncSession,
        context: TenantContext,
        embeddings: EmbeddingProvider,
    ) -> None:
        self._session = session
        self._context = context
        self._embeddings = embeddings

    async def retrieve(self, query: KnowledgeQuery) -> tuple[KnowledgeHit, ...]:
        await set_tenant_context(self._session, self._context.tenant_id)
        await self._session.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{query.timeout_ms}ms"},
        )
        batch = await self._embeddings.embed((query.text,))
        vector = embedding_literal(batch.vectors[0])
        result = await self._session.execute(
            text(
                "WITH ranked AS (SELECT chunk.id, chunk.document_id, chunk.chunk_text, "
                "chunk.content_digest, chunk.source_id, chunk.source_version_id, "
                "chunk.authority, chunk.locator, "
                "1 - (chunk.embedding OPERATOR(extensions.<=>) "
                "CAST(:embedding AS extensions.vector)) AS semantic_score, "
                "CASE chunk.authority WHEN 'AUTHORITATIVE' THEN 0.03 "
                "WHEN 'SECONDARY' THEN 0.015 ELSE 0.0 END AS authority_boost "
                "FROM public.knowledge_chunks AS chunk "
                "JOIN public.knowledge_versions AS version "
                "ON version.tenant_id = chunk.tenant_id "
                "AND version.id = chunk.knowledge_version_id "
                "WHERE chunk.tenant_id = :tenant_id "
                "AND chunk.knowledge_version_id = :version_id "
                "AND version.state IN ('TEST', 'PRODUCTION') "
                "AND version.digest = :knowledge_digest "
                "AND chunk.embedding_model = :embedding_model "
                "AND chunk.embedding_version = :embedding_version) "
                "SELECT id, document_id, chunk_text, content_digest, source_id, "
                "source_version_id, authority, locator, "
                "semantic_score + authority_boost AS score FROM ranked "
                "WHERE semantic_score >= :minimum_score "
                "ORDER BY score DESC, CASE authority "
                "WHEN 'AUTHORITATIVE' THEN 3 WHEN 'SECONDARY' THEN 2 ELSE 1 END DESC, "
                "id LIMIT :top_k"
            ),
            {
                "embedding": vector,
                "tenant_id": self._context.tenant_id,
                "version_id": query.knowledge_version_id,
                "knowledge_digest": query.knowledge_digest,
                "embedding_model": batch.model,
                "embedding_version": batch.version,
                "minimum_score": query.minimum_score,
                "top_k": query.top_k,
            },
        )
        return tuple(
            KnowledgeHit(
                chunk_id=row["id"],
                document_id=row["document_id"],
                text=row["chunk_text"],
                content_digest=row["content_digest"],
                score=float(row["score"]),
                source_id=row["source_id"],
                source_version_id=row["source_version_id"],
                authority=row["authority"],
                locator=row["locator"],
            )
            for row in result.mappings()
        )
