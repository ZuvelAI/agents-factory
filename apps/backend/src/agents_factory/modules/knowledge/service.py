from __future__ import annotations

from datetime import datetime
from uuid import UUID

from agents_factory.common.errors import DomainError
from agents_factory.modules.knowledge.models import (
    AuthorityResolution,
    KnowledgeAuthority,
    KnowledgeDocument,
    KnowledgeDocumentDraft,
    KnowledgeIngestion,
    KnowledgeSource,
    KnowledgeSourceType,
    KnowledgeSourceVersion,
    KnowledgeVersion,
    StructuredFact,
    StructuredFactDraft,
    knowledge_digest,
    resolve_authority,
)
from agents_factory.modules.knowledge.repository import KnowledgeRepository
from agents_factory.modules.knowledge.publishing import (
    FailClosedKnowledgeProductionQualityGate,
    KnowledgeEvalEvidence,
    KnowledgeProductionQualityGate,
    require_production_gate,
)


class KnowledgeService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        *,
        production_gate: KnowledgeProductionQualityGate | None = None,
    ) -> None:
        self._repository = repository
        self._production_gate = (
            production_gate or FailClosedKnowledgeProductionQualityGate()
        )

    async def create_source(
        self,
        *,
        name: str,
        source_type: KnowledgeSourceType,
        authority: KnowledgeAuthority,
        configuration: dict[str, object] | None = None,
    ) -> KnowledgeSource:
        source = await self._repository.create_source(
            name=name,
            source_type=source_type,
            authority=authority,
            configuration=configuration or {},
        )
        await self._repository.audit(
            event_type="knowledge.source.created",
            entity_type="knowledge_source",
            entity_id=source.id,
            payload={"source_type": source_type, "authority": authority},
        )
        return source

    async def request_ingestion(self, source_id: UUID) -> KnowledgeIngestion:
        ingestion = await self._repository.create_ingestion(source_id=source_id)
        if ingestion is None:
            raise _not_found("Knowledge source")
        await self._repository.audit(
            event_type="knowledge.ingestion.requested",
            entity_type="knowledge_ingestion",
            entity_id=ingestion.id,
            payload={"source_id": str(source_id)},
        )
        return ingestion

    async def append_source_version(
        self,
        *,
        source_id: UUID,
        version_number: int,
        content_digest: str,
        verified_at: datetime,
        locator: dict[str, object],
    ) -> KnowledgeSourceVersion:
        actor_id = self._repository.actor_id
        if actor_id is None:
            raise _admin_required()
        version = await self._repository.append_source_version(
            source_id=source_id,
            version_number=version_number,
            content_digest=content_digest,
            verified_at=verified_at,
            approved_by_admin_id=actor_id,
            locator=locator,
        )
        if version is None:
            raise _not_found("Knowledge source")
        await self._repository.audit(
            event_type="knowledge.source_version.approved",
            entity_type="knowledge_source_version",
            entity_id=version.id,
            payload={
                "source_id": str(source_id),
                "version_number": version_number,
                "content_digest": content_digest,
            },
        )
        return version

    async def get_source_version(
        self, *, source_id: UUID, source_version_id: UUID
    ) -> KnowledgeSourceVersion:
        version = await self._repository.get_source_version(
            source_id=source_id,
            source_version_id=source_version_id,
        )
        if version is None:
            raise _not_found("Knowledge source version")
        return version

    async def add_structured_fact(self, draft: StructuredFactDraft) -> StructuredFact:
        fact = await self._repository.add_structured_fact(draft)
        if fact is None:
            raise _provenance_mismatch()
        await self._repository.audit(
            event_type="knowledge.structured_fact.created",
            entity_type="structured_fact",
            entity_id=fact.id,
            payload={"key": fact.key, "kind": fact.kind},
        )
        return fact

    async def add_document(self, draft: KnowledgeDocumentDraft) -> KnowledgeDocument:
        document = await self._repository.add_document(draft)
        if document is None:
            raise _provenance_mismatch()
        await self._repository.audit(
            event_type="knowledge.document.created",
            entity_type="knowledge_document",
            entity_id=document.id,
            payload={"category": document.category, "title": document.title},
        )
        return document

    async def create_version(
        self, *, name: str, based_on_version_id: UUID | None = None
    ) -> KnowledgeVersion:
        if based_on_version_id is not None:
            base = await self._repository.get_version(based_on_version_id)
            if base is None or base.state == "DRAFT":
                raise _not_found("Base Knowledge version")
        version = await self._repository.create_version(
            name=name,
            based_on_version_id=based_on_version_id,
        )
        await self._repository.audit(
            event_type="knowledge.version.created",
            entity_type="knowledge_version",
            entity_id=version.id,
            payload={"version_number": version.version_number},
        )
        return version

    async def add_members(
        self,
        *,
        version_id: UUID,
        structured_fact_ids: tuple[UUID, ...] = (),
        document_ids: tuple[UUID, ...] = (),
    ) -> KnowledgeVersion:
        version = await self._repository.get_version(version_id)
        if version is None:
            raise _not_found("Knowledge version")
        if version.state != "DRAFT":
            raise _invalid_transition(version.state, "ADD_MEMBERS")
        if len(set(structured_fact_ids)) != len(structured_fact_ids) or len(
            set(document_ids)
        ) != len(document_ids):
            raise _invalid_members()
        inserted = await self._repository.add_members(
            version_id=version_id,
            structured_fact_ids=structured_fact_ids,
            document_ids=document_ids,
        )
        if not inserted:
            raise _invalid_members()
        await self._repository.audit(
            event_type="knowledge.version.members_added",
            entity_type="knowledge_version",
            entity_id=version.id,
            payload={
                "structured_fact_count": len(structured_fact_ids),
                "document_count": len(document_ids),
            },
        )
        return version

    async def promote_to_test(
        self,
        version_id: UUID,
        *,
        evidence: KnowledgeEvalEvidence,
    ) -> KnowledgeVersion:
        version = await self._repository.get_version(version_id)
        if version is None:
            raise _not_found("Knowledge version")
        if version.state != "DRAFT":
            raise _invalid_transition(version.state, "TEST")
        if not await self._repository.has_complete_document_embeddings(version_id):
            raise DomainError(
                type="https://agents-factory.dev/problems/knowledge-embeddings-required",
                title="Knowledge Embeddings Required",
                status=409,
                detail=(
                    "Every document in the exact Knowledge version must be embedded "
                    "before entering Test."
                ),
                code="knowledge_embeddings_required",
            )
        digest = knowledge_digest(await self._repository.member_digests(version_id))
        if await self._repository.has_open_critical_conflicts(version_id):
            raise DomainError(
                type="https://agents-factory.dev/problems/knowledge-conflicts-open",
                title="Critical Knowledge Conflicts Are Open",
                status=409,
                detail="Every critical conflict must be explicitly resolved before Test.",
                code="knowledge_conflicts_open",
            )
        if not evidence.matches(digest):
            raise DomainError(
                type="https://agents-factory.dev/problems/knowledge-eval-required",
                title="Knowledge Eval Evidence Required",
                status=409,
                detail="Passing Eval Runner v0 evidence must match the exact Knowledge digest.",
                code="knowledge_eval_required",
            )
        await self._repository.record_eval_evidence(
            evidence_id=evidence.id,
            version_id=version_id,
            knowledge_digest=evidence.knowledge_digest,
            suite_digest=evidence.suite_digest,
            runner_version=evidence.runner_version,
            passed=evidence.passed,
            passed_cases=evidence.passed_cases,
            failed_cases=evidence.failed_cases,
        )
        promoted = await self._repository.promote_to_test(
            version_id=version_id,
            digest=digest,
        )
        if promoted is None:
            raise _invalid_transition(version.state, "TEST")
        await self._repository.audit(
            event_type="knowledge.version.promoted_to_test",
            entity_type="knowledge_version",
            entity_id=version.id,
            payload={"digest": digest},
        )
        return promoted

    async def publish_production(self, version_id: UUID) -> KnowledgeVersion:
        version = await self._repository.get_version(version_id)
        if version is None:
            raise _not_found("Knowledge version")
        if version.state != "TEST" or version.digest is None:
            raise _invalid_transition(version.state, "PRODUCTION")
        await require_production_gate(
            knowledge_digest=version.digest,
            gate=self._production_gate,
        )
        raise _invalid_transition(version.state, "PRODUCTION")

    async def request_embeddings(self, version_id: UUID) -> UUID:
        version = await self._repository.get_version(version_id)
        if version is None:
            raise _not_found("Knowledge version")
        if version.state != "DRAFT":
            raise _invalid_transition(version.state, "EMBED")
        job_id = await self._repository.enqueue_embedding_job(version_id)
        await self._repository.audit(
            event_type="knowledge.embedding.requested",
            entity_type="knowledge_version",
            entity_id=version_id,
            payload={"job_id": str(job_id)},
        )
        return job_id

    async def resolve_fact(self, *, version_id: UUID, key: str) -> AuthorityResolution:
        version = await self._repository.get_version(version_id)
        if version is None or version.state == "DRAFT":
            raise _not_found("Deployable Knowledge version")
        return resolve_authority(
            await self._repository.candidates_for_key(version_id=version_id, key=key)
        )


def _not_found(resource: str) -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/knowledge-not-found",
        title="Knowledge Resource Not Found",
        status=404,
        detail=f"{resource} does not exist in this tenant.",
        code="knowledge_not_found",
    )


def _admin_required() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/knowledge-admin-required",
        title="Knowledge Admin Required",
        status=403,
        detail="An authenticated platform admin must approve Knowledge provenance.",
        code="knowledge_admin_required",
    )


def _provenance_mismatch() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/knowledge-provenance-mismatch",
        title="Knowledge Provenance Mismatch",
        status=409,
        detail="Knowledge provenance must exactly match its approved source version.",
        code="knowledge_provenance_mismatch",
    )


def _invalid_transition(current: str, target: str) -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/invalid-knowledge-transition",
        title="Invalid Knowledge Transition",
        status=409,
        detail=f"Knowledge cannot transition from {current} to {target}.",
        code="invalid_knowledge_transition",
    )


def _invalid_members() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/invalid-knowledge-members",
        title="Invalid Knowledge Members",
        status=422,
        detail="Members must be unique, tenant-owned, and include at least one artifact.",
        code="invalid_knowledge_members",
    )
