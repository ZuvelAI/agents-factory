from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.queue import JobEnvelope, JobHandler
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.knowledge.chunking import KnowledgeChunker
from agents_factory.modules.knowledge.embeddings import (
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    embedding_literal,
)


class InvalidEmbeddingJob(ValueError):
    pass


class EmbeddingProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class _Document:
    id: UUID
    document_text: str
    locator: dict[str, object]


async def configure_embedding_jobs(
    context: dict[Any, Any], *, database: Database
) -> None:
    provider = cast(EmbeddingProvider | None, context.get("embedding_provider"))
    if provider is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            provider = OpenAIEmbeddingProvider(client=AsyncOpenAI(api_key=api_key))

    async def embedding_handler(envelope: JobEnvelope) -> None:
        if provider is None:
            raise EmbeddingProviderUnavailable
        await handle_embedding_job(
            envelope=envelope,
            database=database,
            provider=provider,
        )

    handlers = cast(dict[str, JobHandler], context["job_handlers"])
    handlers["knowledge.embed"] = embedding_handler


async def handle_embedding_job(
    *,
    envelope: JobEnvelope,
    database: Database,
    provider: EmbeddingProvider,
) -> None:
    if envelope.kind != "knowledge.embed":
        raise InvalidEmbeddingJob("unexpected job kind")
    documents = await _load_documents(database=database, envelope=envelope)
    chunker = KnowledgeChunker()
    chunks = tuple(
        chunk
        for document in documents
        for chunk in chunker.chunk(
            document_id=document.id,
            text=document.document_text,
            locator=document.locator,
        )
    )
    embedded = 0
    for start in range(0, len(chunks), 100):
        batch_chunks = chunks[start : start + 100]
        batch = await provider.embed(tuple(chunk.text for chunk in batch_chunks))
        async with database.session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await set_tenant_context(session, envelope.tenant_id)
            statement = text(
                "SELECT agents_factory_private.append_knowledge_chunk("
                ":id, :tenant_id, :version_id, :document_id, :chunk_index, "
                ":chunk_text, :content_digest, :locale, :locator, :embedding, "
                ":embedding_model, :embedding_version)"
            ).bindparams(bindparam("locator", type_=JSONB))
            for chunk, vector in zip(batch_chunks, batch.vectors, strict=True):
                requested_id = new_uuid7()
                chunk_id = await session.scalar(
                    statement,
                    {
                        "id": requested_id,
                        "tenant_id": envelope.tenant_id,
                        "version_id": envelope.aggregate_id,
                        "document_id": chunk.document_id,
                        "chunk_index": chunk.chunk_index,
                        "chunk_text": chunk.text,
                        "content_digest": chunk.content_digest,
                        "locale": chunk.locale,
                        "locator": chunk.locator,
                        "embedding": embedding_literal(vector),
                        "embedding_model": batch.model,
                        "embedding_version": batch.version,
                    },
                )
                embedded += 1 if chunk_id == requested_id else 0
    await _audit_completion(
        database=database,
        envelope=envelope,
        document_count=len(documents),
        chunk_count=len(chunks),
        embedded_count=embedded,
    )


async def _load_documents(
    *, database: Database, envelope: JobEnvelope
) -> tuple[_Document, ...]:
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        state = await session.scalar(
            text(
                "SELECT state FROM public.knowledge_versions "
                "WHERE tenant_id = :tenant_id AND id = :version_id"
            ),
            {
                "tenant_id": envelope.tenant_id,
                "version_id": envelope.aggregate_id,
            },
        )
        if state != "DRAFT":
            raise InvalidEmbeddingJob("embedding requires a Draft Knowledge version")
        rows = (
            await session.execute(
                text(
                    "SELECT document.id, document.document_text, document.locator "
                    "FROM public.knowledge_version_members AS member "
                    "JOIN public.knowledge_documents AS document "
                    "ON document.tenant_id = member.tenant_id "
                    "AND document.id = member.document_id "
                    "WHERE member.tenant_id = :tenant_id "
                    "AND member.knowledge_version_id = :version_id "
                    "ORDER BY member.position, document.id"
                ),
                {
                    "tenant_id": envelope.tenant_id,
                    "version_id": envelope.aggregate_id,
                },
            )
        ).mappings()
        return tuple(
            _Document(
                id=row["id"],
                document_text=row["document_text"],
                locator=row["locator"],
            )
            for row in rows
        )


async def _audit_completion(
    *,
    database: Database,
    envelope: JobEnvelope,
    document_count: int,
    chunk_count: int,
    embedded_count: int,
) -> None:
    async with database.session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, envelope.tenant_id)
        await AuditService(session).record(
            context=TenantContext(
                tenant_id=envelope.tenant_id,
                actor_id=None,
                actor_type="system",
                correlation_id=envelope.job_id,
            ),
            event_type="knowledge.embedding.completed",
            entity_type="knowledge_version",
            entity_id=envelope.aggregate_id,
            payload={
                "document_count": document_count,
                "chunk_count": chunk_count,
                "embedded_count": embedded_count,
            },
        )
