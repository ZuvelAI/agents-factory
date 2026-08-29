from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.modules.knowledge.repository import KnowledgeRepository
from agents_factory.modules.knowledge.service import KnowledgeService


TENANT_ID = UUID("10000000-0000-0000-0000-000000000018")


@pytest.mark.asyncio
async def test_ingestion_request_is_tenant_scoped_and_durably_enqueued(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = TenantContext(
        tenant_id=TENANT_ID,
        actor_id=uuid4(),
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) "
                "VALUES (:id, 'task18', 'Task 18')"
            ),
            {"id": TENANT_ID},
        )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        service = KnowledgeService(KnowledgeRepository(session, context))
        source_record = await service.create_source(
            name="Sitio aprobado",
            source_type="WEBSITE",
            authority="AUTHORITATIVE",
            configuration={"url": "https://example.com/knowledge"},
        )
        ingestion = await service.request_ingestion(source_record.id)
        payload = await session.scalar(
            text(
                "SELECT payload FROM public.outbox_jobs "
                "WHERE tenant_id = :tenant_id AND topic = 'knowledge.ingest'"
            ),
            {"tenant_id": TENANT_ID},
        )

        assert ingestion.state == "PENDING"
        assert payload == {
            "aggregate_id": str(ingestion.id),
            "source_id": str(source_record.id),
        }
