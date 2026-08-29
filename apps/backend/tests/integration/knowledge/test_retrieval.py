from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.modules.knowledge.embeddings import (
    DeterministicEmbeddingProvider,
    embedding_literal,
)
from agents_factory.modules.knowledge.retrieval import (
    KnowledgeQuery,
    KnowledgeRetriever,
)


TENANT_A = UUID("10000000-0000-0000-0000-000000000019")
TENANT_B = UUID("20000000-0000-0000-0000-000000000019")


async def _seed_chunk(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    authority: str,
    vector: str,
) -> tuple[UUID, UUID, UUID]:
    source_id, source_version_id, document_id = uuid4(), uuid4(), uuid4()
    version_id, member_id, chunk_id = uuid4(), uuid4(), uuid4()
    parameters = {
        "tenant_id": tenant_id,
        "source_id": source_id,
        "source_version_id": source_version_id,
        "document_id": document_id,
        "version_id": version_id,
        "member_id": member_id,
        "chunk_id": chunk_id,
        "authority": authority,
        "admin_id": uuid4(),
        "chunk_text": "Los cambios requieren comprobante de compra.",
        "embedding": vector,
        "source_digest": "a" * 64,
        "document_digest": "b" * 64,
        "chunk_digest": "c" * 64,
        "version_digest": "d" * 64,
    }
    statements = (
        "INSERT INTO public.knowledge_sources "
        "(id, tenant_id, name, source_type, authority) "
        "VALUES (:source_id, :tenant_id, 'Manual', 'MANUAL', :authority)",
        "INSERT INTO public.knowledge_source_versions "
        "(id, tenant_id, source_id, version_number, authority, content_digest, "
        "verified_at, approved_by_admin_id) VALUES "
        "(:source_version_id, :tenant_id, :source_id, 1, :authority, "
        ":source_digest, now(), :admin_id)",
        "INSERT INTO public.knowledge_documents "
        "(id, tenant_id, source_id, source_version_id, category, title, "
        "document_text, content_digest) VALUES "
        "(:document_id, :tenant_id, :source_id, :source_version_id, 'POLICY', "
        "'Cambios', :chunk_text, :document_digest)",
        "INSERT INTO public.knowledge_versions "
        "(id, tenant_id, name, version_number, state) "
        "VALUES (:version_id, :tenant_id, 'Knowledge Test', 1, 'DRAFT')",
        "INSERT INTO public.knowledge_version_members "
        "(id, tenant_id, knowledge_version_id, document_id, position) "
        "VALUES (:member_id, :tenant_id, :version_id, :document_id, 0)",
        "INSERT INTO public.knowledge_chunks "
        "(id, tenant_id, knowledge_version_id, document_id, source_id, "
        "source_version_id, authority, chunk_index, chunk_text, content_digest, "
        "locale, locator, embedding, embedding_model, embedding_version) VALUES "
        "(:chunk_id, :tenant_id, :version_id, :document_id, :source_id, "
        ":source_version_id, :authority, 0, :chunk_text, :chunk_digest, 'es-CO', "
        "'{\"page\": 1}'::jsonb, CAST(:embedding AS extensions.vector), "
        "'deterministic-sha256', '1')",
        "UPDATE public.knowledge_versions SET state = 'TEST', "
        "digest = :version_digest WHERE id = :version_id",
    )
    for statement in statements:
        await session.execute(text(statement), parameters)
    return version_id, source_id, source_version_id


@pytest.mark.asyncio
async def test_retrieval_is_bound_to_exact_tenant_version_and_provenance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    query_text = "Los cambios requieren comprobante de compra."
    provider = DeterministicEmbeddingProvider()
    vector = embedding_literal((await provider.embed((query_text,))).vectors[0])
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) VALUES "
                "(:tenant_a, 'retrieval-a', 'Retrieval A'), "
                "(:tenant_b, 'retrieval-b', 'Retrieval B')"
            ),
            {"tenant_a": TENANT_A, "tenant_b": TENANT_B},
        )
        version_a, source_a, source_version_a = await _seed_chunk(
            session,
            tenant_id=TENANT_A,
            authority="AUTHORITATIVE",
            vector=vector,
        )
        await _seed_chunk(
            session,
            tenant_id=TENANT_B,
            authority="REFERENCE",
            vector=vector,
        )

    context = TenantContext(
        tenant_id=TENANT_A,
        actor_id=None,
        actor_type="system",
        correlation_id=uuid4(),
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        hits = await KnowledgeRetriever(
            session=session,
            context=context,
            embeddings=provider,
        ).retrieve(
            KnowledgeQuery(
                knowledge_version_id=version_a,
                knowledge_digest="d" * 64,
                text=query_text,
                minimum_score=0.9,
            )
        )

    assert len(hits) == 1
    assert hits[0].source_id == source_a
    assert hits[0].source_version_id == source_version_a
    assert hits[0].authority == "AUTHORITATIVE"
    assert hits[0].locator == {"page": 1}
