from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.asyncio
async def test_vector_rows_are_invisible_without_matching_tenant_context(
    conversation_database_engine: AsyncEngine,
    clean_conversation_tables: None,
) -> None:
    tenant_a, tenant_b = uuid4(), uuid4()
    source_a, source_b = uuid4(), uuid4()
    source_version_a, source_version_b = uuid4(), uuid4()
    document_a, document_b = uuid4(), uuid4()
    version_a, version_b = uuid4(), uuid4()
    chunk_a, chunk_b = uuid4(), uuid4()
    zero_vector = "[" + ",".join(("0",) * 1_536) + "]"
    parameters = {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "source_a": source_a,
        "source_b": source_b,
        "source_version_a": source_version_a,
        "source_version_b": source_version_b,
        "document_a": document_a,
        "document_b": document_b,
        "version_a": version_a,
        "version_b": version_b,
        "chunk_a": chunk_a,
        "chunk_b": chunk_b,
        "admin": uuid4(),
        "embedding": zero_vector,
        "digest_a": "a" * 64,
        "digest_b": "b" * 64,
        "digest_c": "c" * 64,
        "digest_d": "d" * 64,
        "digest_e": "e" * 64,
        "digest_f": "f" * 64,
    }
    statements = (
        "INSERT INTO public.tenants (id, slug, name) VALUES "
        "(:tenant_a, 'vector-a', 'Vector A'), "
        "(:tenant_b, 'vector-b', 'Vector B')",
        "INSERT INTO public.knowledge_sources "
        "(id, tenant_id, name, source_type, authority) VALUES "
        "(:source_a, :tenant_a, 'A', 'MANUAL', 'AUTHORITATIVE'), "
        "(:source_b, :tenant_b, 'B', 'MANUAL', 'AUTHORITATIVE')",
        "INSERT INTO public.knowledge_source_versions "
        "(id, tenant_id, source_id, version_number, authority, content_digest, "
        "verified_at, approved_by_admin_id) VALUES "
        "(:source_version_a, :tenant_a, :source_a, 1, 'AUTHORITATIVE', "
        ":digest_a, now(), :admin), "
        "(:source_version_b, :tenant_b, :source_b, 1, 'AUTHORITATIVE', "
        ":digest_b, now(), :admin)",
        "INSERT INTO public.knowledge_documents "
        "(id, tenant_id, source_id, source_version_id, category, title, "
        "document_text, content_digest) VALUES "
        "(:document_a, :tenant_a, :source_a, :source_version_a, "
        "'POLICY', 'A', 'same text', :digest_c), "
        "(:document_b, :tenant_b, :source_b, :source_version_b, "
        "'POLICY', 'B', 'same text', :digest_d)",
        "INSERT INTO public.knowledge_versions "
        "(id, tenant_id, name, version_number, state) VALUES "
        "(:version_a, :tenant_a, 'A', 1, 'DRAFT'), "
        "(:version_b, :tenant_b, 'B', 1, 'DRAFT')",
        "INSERT INTO public.knowledge_chunks "
        "(id, tenant_id, knowledge_version_id, document_id, source_id, "
        "source_version_id, authority, chunk_index, chunk_text, content_digest, "
        "locale, locator, embedding, embedding_model, embedding_version) VALUES "
        "(:chunk_a, :tenant_a, :version_a, :document_a, :source_a, "
        ":source_version_a, 'AUTHORITATIVE', 0, 'same text', :digest_e, 'en-US', "
        "'{}'::jsonb, CAST(:embedding AS extensions.vector), 'test', '1'), "
        "(:chunk_b, :tenant_b, :version_b, :document_b, :source_b, "
        ":source_version_b, 'AUTHORITATIVE', 0, 'same text', :digest_f, 'en-US', "
        "'{}'::jsonb, CAST(:embedding AS extensions.vector), 'test', '1')",
    )
    async with conversation_database_engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement), parameters)

    async with conversation_database_engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE agents_factory_app"))
        await connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_a)},
        )
        visible = tuple(
            (
                await connection.execute(
                    text("SELECT id FROM public.knowledge_chunks ORDER BY id")
                )
            ).scalars()
        )
        assert visible == (chunk_a,)

    async with conversation_database_engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE agents_factory_app"))
        assert (
            await connection.scalar(
                text("SELECT count(*) FROM public.knowledge_chunks")
            )
            == 0
        )
