from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.modules.knowledge.models import (
    KnowledgeDocumentDraft,
    KnowledgeProvenance,
    StructuredFactDraft,
    knowledge_digest,
)
from agents_factory.modules.knowledge.publishing import KnowledgeEvalEvidence
from agents_factory.modules.knowledge.repository import KnowledgeRepository
from agents_factory.modules.knowledge.service import KnowledgeService


TENANT_ID = UUID("10000000-0000-0000-0000-000000000017")


@pytest.mark.asyncio
async def test_sources_are_versioned_and_versions_bind_immutable_provenance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor_id = uuid4()
    context = TenantContext(
        tenant_id=TENANT_ID,
        actor_id=actor_id,
        actor_type="platform_admin",
        correlation_id=uuid4(),
    )
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) "
                "VALUES (:id, 'task17', 'Task 17')"
            ),
            {"id": TENANT_ID},
        )

    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        repository = KnowledgeRepository(session, context)
        service = KnowledgeService(repository)
        source = await service.create_source(
            name="Manual operativo aprobado",
            source_type="MANUAL",
            authority="AUTHORITATIVE",
        )
        source_version = await service.append_source_version(
            source_id=source.id,
            version_number=1,
            content_digest="a" * 64,
            verified_at=datetime(2026, 8, 29, tzinfo=UTC),
            locator={"section": "Operaciones"},
        )
        provenance = KnowledgeProvenance(
            source_id=source.id,
            source_version_id=source_version.id,
            authority=source_version.authority,
            verified_at=source_version.verified_at,
            approved_by_admin_id=source_version.approved_by_admin_id,
            content_digest="b" * 64,
        )
        hours = await service.add_structured_fact(
            StructuredFactDraft(
                key="operations.business_hours.main",
                kind="BUSINESS_HOURS",
                value={"monday": {"opens": "08:00", "closes": "17:00"}},
                provenance=provenance,
            )
        )
        policy = await service.add_document(
            KnowledgeDocumentDraft(
                category="POLICY",
                title="Política de devoluciones",
                text="Las devoluciones requieren comprobante.",
                locator={"section": "Devoluciones"},
                provenance=provenance.model_copy(update={"content_digest": "c" * 64}),
            )
        )
        version = await service.create_version(name="Standard v1")
        version = await service.add_members(
            version_id=version.id,
            structured_fact_ids=(hours.id,),
        )
        test_version = await service.promote_to_test(
            version.id,
            evidence=KnowledgeEvalEvidence(
                id=uuid4(),
                knowledge_digest=knowledge_digest(("b" * 64,)),
                suite_digest="e" * 64,
                runner_version="0.1.0",
                passed=True,
                passed_cases=1,
                failed_cases=0,
            ),
        )

        assert test_version.state == "TEST"
        assert test_version.digest is not None
        assert hours.provenance.approved_by_admin_id == actor_id
        assert policy.provenance.source_version_id == source_version.id
