from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from agents_factory.modules.knowledge.models import (
    AuthorityCandidate,
    KnowledgeAuthority,
    KnowledgeDocument,
    KnowledgeDocumentDraft,
    KnowledgeIngestion,
    KnowledgeProvenance,
    KnowledgeSource,
    KnowledgeSourceType,
    KnowledgeSourceVersion,
    KnowledgeVersion,
    StructuredFact,
    StructuredFactDraft,
)


class KnowledgeRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context
        self._audit = AuditService(session)
        self._outbox = OutboxService(session)

    async def create_source(
        self,
        *,
        name: str,
        source_type: KnowledgeSourceType,
        authority: KnowledgeAuthority,
        configuration: Mapping[str, object],
    ) -> KnowledgeSource:
        await self._scope()
        result = await self._session.execute(
            text(
                "INSERT INTO public.knowledge_sources "
                "(id, tenant_id, name, source_type, authority, configuration) "
                "VALUES (:id, :tenant_id, :name, :source_type, :authority, "
                ":configuration) RETURNING id, tenant_id, name, source_type, "
                "authority, configuration, created_at"
            ).bindparams(bindparam("configuration", type_=JSONB)),
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "name": name,
                "source_type": source_type,
                "authority": authority,
                "configuration": dict(configuration),
            },
        )
        return KnowledgeSource.from_mapping(result.mappings().one())

    async def get_source(self, source_id: UUID) -> KnowledgeSource | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, name, source_type, authority, configuration, "
                "created_at "
                "FROM public.knowledge_sources "
                "WHERE tenant_id = :tenant_id AND id = :source_id"
            ),
            {"tenant_id": self._context.tenant_id, "source_id": source_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else KnowledgeSource.from_mapping(row)

    async def create_ingestion(self, *, source_id: UUID) -> KnowledgeIngestion | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "INSERT INTO public.knowledge_ingestions "
                "(id, tenant_id, source_id, state) SELECT :id, source.tenant_id, "
                "source.id, 'PENDING' FROM public.knowledge_sources AS source "
                "WHERE source.tenant_id = :tenant_id AND source.id = :source_id "
                "RETURNING id, tenant_id, source_id, state, content_digest, "
                "storage_path, proposed_artifact_count, error_code, created_at, "
                "updated_at, completed_at"
            ),
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "source_id": source_id,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        ingestion = KnowledgeIngestion.from_mapping(row)
        await self._outbox.enqueue(
            context=self._context,
            idempotency_key=f"knowledge.ingest:{ingestion.id}",
            topic="knowledge.ingest",
            payload={
                "aggregate_id": str(ingestion.id),
                "source_id": str(source_id),
            },
        )
        return ingestion

    async def append_source_version(
        self,
        *,
        source_id: UUID,
        version_number: int,
        content_digest: str,
        verified_at: datetime,
        approved_by_admin_id: UUID,
        locator: Mapping[str, object],
    ) -> KnowledgeSourceVersion | None:
        await self._scope()
        statement = text(
            "INSERT INTO public.knowledge_source_versions "
            "(id, tenant_id, source_id, version_number, authority, content_digest, "
            "verified_at, approved_by_admin_id, locator) "
            "SELECT :id, source.tenant_id, source.id, :version_number, "
            "source.authority, :content_digest, :verified_at, :approved_by, :locator "
            "FROM public.knowledge_sources AS source "
            "WHERE source.tenant_id = :tenant_id AND source.id = :source_id "
            "RETURNING id, tenant_id, source_id, version_number, authority, "
            "content_digest, verified_at, approved_by_admin_id, locator, created_at"
        ).bindparams(bindparam("locator", type_=JSONB))
        result = await self._session.execute(
            statement,
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "source_id": source_id,
                "version_number": version_number,
                "content_digest": content_digest,
                "verified_at": verified_at,
                "approved_by": approved_by_admin_id,
                "locator": dict(locator),
            },
        )
        row = result.mappings().one_or_none()
        return None if row is None else KnowledgeSourceVersion.from_mapping(row)

    async def get_source_version(
        self, *, source_id: UUID, source_version_id: UUID
    ) -> KnowledgeSourceVersion | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, source_id, version_number, authority, "
                "content_digest, verified_at, approved_by_admin_id, locator, created_at "
                "FROM public.knowledge_source_versions WHERE tenant_id = :tenant_id "
                "AND source_id = :source_id AND id = :source_version_id"
            ),
            {
                "tenant_id": self._context.tenant_id,
                "source_id": source_id,
                "source_version_id": source_version_id,
            },
        )
        row = result.mappings().one_or_none()
        return None if row is None else KnowledgeSourceVersion.from_mapping(row)

    async def add_structured_fact(
        self, draft: StructuredFactDraft
    ) -> StructuredFact | None:
        await self._scope()
        provenance = draft.provenance
        statement = text(
            "INSERT INTO public.structured_facts "
            "(id, tenant_id, source_id, source_version_id, key, kind, value, "
            "content_digest) SELECT :id, version.tenant_id, version.source_id, "
            "version.id, :key, :kind, :value, :content_digest "
            "FROM public.knowledge_source_versions AS version "
            "WHERE version.tenant_id = :tenant_id AND version.source_id = :source_id "
            "AND version.id = :source_version_id AND version.authority = :authority "
            "AND version.verified_at = :verified_at "
            "AND version.approved_by_admin_id = :approved_by "
            "RETURNING id, tenant_id, key, kind, value, source_id, "
            "source_version_id, content_digest, created_at"
        ).bindparams(bindparam("value", type_=JSONB))
        result = await self._session.execute(
            statement,
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "source_id": provenance.source_id,
                "source_version_id": provenance.source_version_id,
                "authority": provenance.authority,
                "verified_at": provenance.verified_at,
                "approved_by": provenance.approved_by_admin_id,
                "key": draft.key,
                "kind": draft.kind,
                "value": draft.value,
                "content_digest": provenance.content_digest,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return StructuredFact(
            id=row["id"],
            tenant_id=row["tenant_id"],
            key=row["key"],
            kind=row["kind"],
            value=row["value"],
            provenance=provenance,
            created_at=row["created_at"],
        )

    async def add_document(
        self, draft: KnowledgeDocumentDraft
    ) -> KnowledgeDocument | None:
        await self._scope()
        provenance = draft.provenance
        statement = text(
            "INSERT INTO public.knowledge_documents "
            "(id, tenant_id, source_id, source_version_id, category, title, "
            "document_text, locator, content_digest) SELECT :id, version.tenant_id, "
            "version.source_id, version.id, :category, :title, :document_text, "
            ":locator, :content_digest FROM public.knowledge_source_versions AS version "
            "WHERE version.tenant_id = :tenant_id AND version.source_id = :source_id "
            "AND version.id = :source_version_id AND version.authority = :authority "
            "AND version.verified_at = :verified_at "
            "AND version.approved_by_admin_id = :approved_by "
            "RETURNING id, tenant_id, category, title, document_text, locator, "
            "source_id, source_version_id, content_digest, created_at"
        ).bindparams(bindparam("locator", type_=JSONB))
        result = await self._session.execute(
            statement,
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "source_id": provenance.source_id,
                "source_version_id": provenance.source_version_id,
                "authority": provenance.authority,
                "verified_at": provenance.verified_at,
                "approved_by": provenance.approved_by_admin_id,
                "category": draft.category,
                "title": draft.title,
                "document_text": draft.text,
                "locator": draft.locator,
                "content_digest": provenance.content_digest,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return KnowledgeDocument(
            id=row["id"],
            tenant_id=row["tenant_id"],
            category=row["category"],
            title=row["title"],
            text=row["document_text"],
            locator=row["locator"],
            provenance=provenance,
            created_at=row["created_at"],
        )

    async def create_version(
        self, *, name: str, based_on_version_id: UUID | None
    ) -> KnowledgeVersion:
        await self._scope()
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"knowledge:{self._context.tenant_id}"},
        )
        result = await self._session.execute(
            text(
                "INSERT INTO public.knowledge_versions "
                "(id, tenant_id, name, version_number, state, based_on_version_id) "
                "SELECT :id, :tenant_id, :name, coalesce(max(version_number), 0) + 1, "
                "'DRAFT', :based_on FROM public.knowledge_versions "
                "WHERE tenant_id = :tenant_id RETURNING id, tenant_id, name, "
                "version_number, state, digest, based_on_version_id, created_at, updated_at"
            ),
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "name": name,
                "based_on": based_on_version_id,
            },
        )
        return KnowledgeVersion.from_mapping(result.mappings().one())

    async def get_version(self, version_id: UUID) -> KnowledgeVersion | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, name, version_number, state, digest, "
                "based_on_version_id, created_at, updated_at "
                "FROM public.knowledge_versions "
                "WHERE tenant_id = :tenant_id AND id = :version_id"
            ),
            {"tenant_id": self._context.tenant_id, "version_id": version_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else KnowledgeVersion.from_mapping(row)

    async def add_members(
        self,
        *,
        version_id: UUID,
        structured_fact_ids: tuple[UUID, ...],
        document_ids: tuple[UUID, ...],
    ) -> bool:
        await self._scope()
        artifacts = tuple(("fact", value) for value in structured_fact_ids) + tuple(
            ("document", value) for value in document_ids
        )
        if not artifacts:
            return False
        position = cast(
            int,
            await self._session.scalar(
                text(
                    "SELECT coalesce(max(position), -1) + 1 "
                    "FROM public.knowledge_version_members "
                    "WHERE tenant_id = :tenant_id AND knowledge_version_id = :version_id"
                ),
                {"tenant_id": self._context.tenant_id, "version_id": version_id},
            ),
        )
        inserted = 0
        for offset, (artifact_type, artifact_id) in enumerate(artifacts):
            result = await self._session.execute(
                text(
                    "INSERT INTO public.knowledge_version_members "
                    "(id, tenant_id, knowledge_version_id, structured_fact_id, "
                    "document_id, position) SELECT :id, version.tenant_id, version.id, "
                    "CASE WHEN :artifact_type = 'fact' THEN artifact.id END, "
                    "CASE WHEN :artifact_type = 'document' THEN artifact.id END, "
                    ":position FROM public.knowledge_versions AS version "
                    "JOIN LATERAL (SELECT id, tenant_id FROM public.structured_facts "
                    "WHERE :artifact_type = 'fact' AND tenant_id = version.tenant_id "
                    "AND id = :artifact_id UNION ALL SELECT id, tenant_id "
                    "FROM public.knowledge_documents WHERE :artifact_type = 'document' "
                    "AND tenant_id = version.tenant_id AND id = :artifact_id) AS artifact "
                    "ON true WHERE version.tenant_id = :tenant_id "
                    "AND version.id = :version_id AND version.state = 'DRAFT' RETURNING id"
                ),
                {
                    "id": new_uuid7(),
                    "tenant_id": self._context.tenant_id,
                    "version_id": version_id,
                    "artifact_type": artifact_type,
                    "artifact_id": artifact_id,
                    "position": position + offset,
                },
            )
            inserted += 1 if result.scalar_one_or_none() is not None else 0
        return inserted == len(artifacts)

    async def member_digests(self, version_id: UUID) -> tuple[str, ...]:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT coalesce(fact.content_digest, document.content_digest) "
                "FROM public.knowledge_version_members AS member "
                "LEFT JOIN public.structured_facts AS fact ON fact.tenant_id = member.tenant_id "
                "AND fact.id = member.structured_fact_id "
                "LEFT JOIN public.knowledge_documents AS document "
                "ON document.tenant_id = member.tenant_id AND document.id = member.document_id "
                "WHERE member.tenant_id = :tenant_id "
                "AND member.knowledge_version_id = :version_id ORDER BY member.position"
            ),
            {"tenant_id": self._context.tenant_id, "version_id": version_id},
        )
        return tuple(cast(str, value) for value in result.scalars())

    async def enqueue_embedding_job(self, version_id: UUID) -> UUID:
        job = await self._outbox.enqueue(
            context=self._context,
            idempotency_key=f"knowledge.embed:{version_id}",
            topic="knowledge.embed",
            payload={"aggregate_id": str(version_id)},
        )
        return job.id

    async def has_complete_document_embeddings(self, version_id: UUID) -> bool:
        await self._scope()
        missing = await self._session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 "
                "FROM public.knowledge_version_members AS member "
                "WHERE member.tenant_id = :tenant_id "
                "AND member.knowledge_version_id = :version_id "
                "AND member.document_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM public.knowledge_chunks AS chunk "
                "WHERE chunk.tenant_id = member.tenant_id "
                "AND chunk.knowledge_version_id = member.knowledge_version_id "
                "AND chunk.document_id = member.document_id))"
            ),
            {"tenant_id": self._context.tenant_id, "version_id": version_id},
        )
        return not bool(missing)

    async def has_open_critical_conflicts(self, version_id: UUID) -> bool:
        await self._scope()
        return bool(
            await self._session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM public.knowledge_conflicts AS conflict "
                    "JOIN public.knowledge_proposals AS proposal "
                    "ON proposal.tenant_id = conflict.tenant_id "
                    "AND proposal.id = conflict.proposal_id "
                    "JOIN public.knowledge_source_diffs AS diff "
                    "ON diff.tenant_id = proposal.tenant_id "
                    "AND diff.ingestion_id = proposal.ingestion_id "
                    "WHERE conflict.tenant_id = :tenant_id "
                    "AND diff.draft_version_id = :version_id "
                    "AND conflict.critical AND conflict.state = 'OPEN')"
                ),
                {
                    "tenant_id": self._context.tenant_id,
                    "version_id": version_id,
                },
            )
        )

    async def record_eval_evidence(
        self,
        *,
        evidence_id: UUID,
        version_id: UUID,
        knowledge_digest: str,
        suite_digest: str,
        runner_version: str,
        passed: bool,
        passed_cases: int,
        failed_cases: int,
    ) -> None:
        await self._scope()
        await self._session.execute(
            text(
                "INSERT INTO public.knowledge_eval_evidence "
                "(id, tenant_id, knowledge_version_id, knowledge_digest, suite_digest, "
                "runner_version, passed, passed_cases, failed_cases) VALUES "
                "(:id, :tenant_id, :version_id, :knowledge_digest, :suite_digest, "
                ":runner_version, :passed, :passed_cases, :failed_cases)"
            ),
            {
                "id": evidence_id,
                "tenant_id": self._context.tenant_id,
                "version_id": version_id,
                "knowledge_digest": knowledge_digest,
                "suite_digest": suite_digest,
                "runner_version": runner_version,
                "passed": passed,
                "passed_cases": passed_cases,
                "failed_cases": failed_cases,
            },
        )

    async def promote_to_test(
        self, *, version_id: UUID, digest: str
    ) -> KnowledgeVersion | None:
        await self._scope()
        result = await self._session.execute(
            text(
                "UPDATE public.knowledge_versions SET state = 'TEST', digest = :digest, "
                "updated_at = now() WHERE tenant_id = :tenant_id AND id = :version_id "
                "AND state = 'DRAFT' RETURNING id, tenant_id, name, version_number, "
                "state, digest, based_on_version_id, created_at, updated_at"
            ),
            {
                "tenant_id": self._context.tenant_id,
                "version_id": version_id,
                "digest": digest,
            },
        )
        row = result.mappings().one_or_none()
        return None if row is None else KnowledgeVersion.from_mapping(row)

    async def candidates_for_key(
        self, *, version_id: UUID, key: str
    ) -> tuple[AuthorityCandidate, ...]:
        await self._scope()
        result = await self._session.execute(
            text(
                "SELECT fact.id, fact.key, fact.value, fact.source_id, "
                "fact.source_version_id, fact.content_digest, source.authority, "
                "source.verified_at, source.approved_by_admin_id "
                "FROM public.knowledge_version_members AS member "
                "JOIN public.structured_facts AS fact ON fact.tenant_id = member.tenant_id "
                "AND fact.id = member.structured_fact_id "
                "JOIN public.knowledge_source_versions AS source "
                "ON source.tenant_id = fact.tenant_id "
                "AND source.id = fact.source_version_id "
                "WHERE member.tenant_id = :tenant_id "
                "AND member.knowledge_version_id = :version_id AND fact.key = :key "
                "ORDER BY fact.id"
            ),
            {
                "tenant_id": self._context.tenant_id,
                "version_id": version_id,
                "key": key,
            },
        )
        return tuple(
            AuthorityCandidate(
                id=row["id"],
                key=row["key"],
                value=row["value"],
                provenance=KnowledgeProvenance(
                    source_id=row["source_id"],
                    source_version_id=row["source_version_id"],
                    authority=row["authority"],
                    verified_at=row["verified_at"],
                    approved_by_admin_id=row["approved_by_admin_id"],
                    content_digest=row["content_digest"],
                ),
            )
            for row in result.mappings()
        )

    async def audit(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
        payload: Mapping[str, object],
    ) -> None:
        await self._audit.record(
            context=self._context,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )

    async def _scope(self) -> None:
        await set_tenant_context(self._session, self._context.tenant_id)

    @property
    def actor_id(self) -> UUID | None:
        return self._context.actor_id
