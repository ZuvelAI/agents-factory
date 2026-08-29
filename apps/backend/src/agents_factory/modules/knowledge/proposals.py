from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.knowledge.conflicts import (
    ExistingFact,
    KnowledgeConflictDraft,
    ProposedFactValue,
    detect_fact_conflicts,
)
from agents_factory.modules.knowledge.ingestion.contracts import (
    ProposedDocument,
    ProposedFact,
)


ProposalArtifactType = Literal["FACT", "DOCUMENT"]
ProposalState = Literal["PROPOSED", "APPROVED", "EDITED", "REJECTED"]
ProposalDecision = Literal["APPROVE", "EDIT", "REJECT"]


class ProposalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KnowledgeProposal(ProposalModel):
    id: UUID
    tenant_id: UUID
    ingestion_artifact_id: UUID
    ingestion_id: UUID
    source_id: UUID
    revision: int = Field(ge=1)
    artifact_type: ProposalArtifactType
    state: ProposalState
    proposed_payload: dict[str, object]
    decision_payload: dict[str, object] | None
    proposed_by: Literal["NORMALIZER", "AI"]
    model_metadata: dict[str, object]
    content_digest: str = Field(pattern=r"[0-9a-f]{64}")
    decided_by_admin_id: UUID | None

    @classmethod
    def from_mapping(cls, row: RowMapping) -> KnowledgeProposal:
        return cls.model_validate(dict(row))


class ProposalReview(ProposalModel):
    revision: int = Field(ge=1)
    decision: ProposalDecision
    edited_payload: dict[str, object] | None = None

    @model_validator(mode="after")
    def edit_requires_payload(self) -> ProposalReview:
        if (self.decision == "EDIT") != (self.edited_payload is not None):
            raise ValueError("only EDIT decisions require an edited payload")
        return self


def validated_payload(
    *,
    artifact_type: ProposalArtifactType,
    payload: dict[str, object],
) -> ProposedFact | ProposedDocument:
    if artifact_type == "FACT":
        return ProposedFact.model_validate(payload)
    return ProposedDocument.model_validate(payload)


def reviewed_payload(
    proposal: KnowledgeProposal,
    review: ProposalReview,
) -> ProposedFact | ProposedDocument:
    payload = (
        proposal.proposed_payload
        if review.edited_payload is None
        else review.edited_payload
    )
    validated = validated_payload(
        artifact_type=proposal.artifact_type,
        payload=payload,
    )
    if validated.source_id != proposal.source_id:
        raise ValueError("a proposal edit cannot change its source")
    return validated


def payload_digest(payload: ProposedFact | ProposedDocument) -> str:
    value = payload.model_dump(mode="json", exclude={"content_digest"})
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class KnowledgeProposalService:
    def __init__(self, *, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def review(
        self,
        *,
        proposal_id: UUID,
        review: ProposalReview,
    ) -> KnowledgeProposal:
        if self._context.actor_id is None:
            raise _review_error("knowledge_admin_required", 403)
        await set_tenant_context(self._session, self._context.tenant_id)
        proposal = await self._locked_proposal(proposal_id)
        if proposal is None:
            raise _review_error("knowledge_proposal_not_found", 404)
        if proposal.state != "PROPOSED" or proposal.revision != review.revision:
            raise _review_error("knowledge_proposal_already_decided", 409)

        payload = reviewed_payload(proposal, review)
        conflicts: tuple[KnowledgeConflictDraft, ...] = ()
        if isinstance(payload, ProposedFact):
            conflicts = detect_fact_conflicts(
                ProposedFactValue(
                    proposal_id=proposal.id,
                    key=payload.key,
                    value=payload.value,
                    authority=payload.authority,
                ),
                await self._existing_facts(payload.key),
            )
            await self._record_conflicts(conflicts)

        decided = await self._close_revision(
            proposal=proposal,
            review=review,
            payload=payload,
        )
        if review.decision != "REJECT":
            await self._materialize(
                proposal=proposal,
                payload=payload,
                edited=review.decision == "EDIT",
            )
        await self._resolve_conflicts(
            proposal_id=proposal.id,
            resolution={
                "APPROVE": "APPROVED",
                "EDIT": "EDITED",
                "REJECT": "REJECTED",
            }[review.decision],
        )
        await AuditService(self._session).record(
            context=self._context,
            event_type="knowledge.proposal.reviewed",
            entity_type="knowledge_proposal",
            entity_id=proposal.id,
            payload={
                "decision": review.decision,
                "revision": review.revision,
                "conflict_count": len(conflicts),
            },
        )
        return decided

    async def _locked_proposal(self, proposal_id: UUID) -> KnowledgeProposal | None:
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, ingestion_artifact_id, ingestion_id, "
                "source_id, revision, artifact_type, state, proposed_payload, "
                "decision_payload, proposed_by, model_metadata, content_digest, "
                "decided_by_admin_id FROM public.knowledge_proposals "
                "WHERE tenant_id = :tenant_id AND id = :proposal_id FOR UPDATE"
            ),
            {"tenant_id": self._context.tenant_id, "proposal_id": proposal_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else KnowledgeProposal.from_mapping(row)

    async def _existing_facts(self, key: str) -> tuple[ExistingFact, ...]:
        result = await self._session.execute(
            text(
                "SELECT DISTINCT fact.id, fact.key, fact.value, source.authority "
                "FROM public.knowledge_version_members AS member "
                "JOIN public.knowledge_versions AS version "
                "ON version.tenant_id = member.tenant_id "
                "AND version.id = member.knowledge_version_id "
                "JOIN public.structured_facts AS fact "
                "ON fact.tenant_id = member.tenant_id "
                "AND fact.id = member.structured_fact_id "
                "JOIN public.knowledge_source_versions AS source "
                "ON source.tenant_id = fact.tenant_id "
                "AND source.id = fact.source_version_id "
                "WHERE member.tenant_id = :tenant_id AND fact.key = :key "
                "AND version.state IN ('TEST', 'PRODUCTION') ORDER BY fact.id"
            ),
            {"tenant_id": self._context.tenant_id, "key": key},
        )
        return tuple(
            ExistingFact.model_validate(dict(row)) for row in result.mappings()
        )

    async def _record_conflicts(
        self, conflicts: tuple[KnowledgeConflictDraft, ...]
    ) -> None:
        statement = text(
            "INSERT INTO public.knowledge_conflicts "
            "(id, tenant_id, proposal_id, fact_key, critical, proposed_authority, "
            "existing_authority, existing_fact_id, details) VALUES "
            "(:id, :tenant_id, :proposal_id, :fact_key, :critical, "
            ":proposed_authority, :existing_authority, :existing_fact_id, :details) "
            "ON CONFLICT (tenant_id, proposal_id, existing_fact_id) DO NOTHING"
        ).bindparams(bindparam("details", type_=JSONB))
        for conflict in conflicts:
            await self._session.execute(
                statement,
                {
                    "id": new_uuid7(),
                    "tenant_id": self._context.tenant_id,
                    "proposal_id": conflict.proposal_id,
                    "fact_key": conflict.fact_key,
                    "critical": conflict.critical,
                    "proposed_authority": conflict.proposed_authority,
                    "existing_authority": conflict.existing_authority,
                    "existing_fact_id": conflict.existing_fact_id,
                    "details": {"reason": conflict.reason},
                },
            )

    async def _close_revision(
        self,
        *,
        proposal: KnowledgeProposal,
        review: ProposalReview,
        payload: ProposedFact | ProposedDocument,
    ) -> KnowledgeProposal:
        state = {"APPROVE": "APPROVED", "EDIT": "EDITED", "REJECT": "REJECTED"}[
            review.decision
        ]
        decision_payload = payload.model_dump(mode="json")
        result = await self._session.execute(
            text(
                "UPDATE public.knowledge_proposals SET state = :state, "
                "decision_payload = :decision_payload, decided_by_admin_id = :admin_id, "
                "decided_at = :decided_at WHERE tenant_id = :tenant_id "
                "AND id = :proposal_id AND revision = :revision "
                "AND state = 'PROPOSED' RETURNING id, tenant_id, "
                "ingestion_artifact_id, ingestion_id, source_id, revision, "
                "artifact_type, state, proposed_payload, decision_payload, proposed_by, "
                "model_metadata, content_digest, decided_by_admin_id"
            ).bindparams(bindparam("decision_payload", type_=JSONB)),
            {
                "state": state,
                "decision_payload": decision_payload,
                "admin_id": self._context.actor_id,
                "decided_at": datetime.now(UTC),
                "tenant_id": self._context.tenant_id,
                "proposal_id": proposal.id,
                "revision": proposal.revision,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise _review_error("knowledge_proposal_already_decided", 409)
        return KnowledgeProposal.from_mapping(row)

    async def _materialize(
        self,
        *,
        proposal: KnowledgeProposal,
        payload: ProposedFact | ProposedDocument,
        edited: bool,
    ) -> None:
        draft_version_id = await self._draft_version(proposal)
        source_version = await self._approved_source_version(proposal)
        content_digest = payload_digest(payload) if edited else payload.content_digest
        artifact_id = new_uuid7()
        if isinstance(payload, ProposedFact):
            await self._session.execute(
                text(
                    "INSERT INTO public.structured_facts "
                    "(id, tenant_id, source_id, source_version_id, key, kind, value, "
                    "content_digest) VALUES (:id, :tenant_id, :source_id, "
                    ":source_version_id, :key, :kind, :value, :content_digest)"
                ).bindparams(bindparam("value", type_=JSONB)),
                {
                    "id": artifact_id,
                    "tenant_id": self._context.tenant_id,
                    "source_id": proposal.source_id,
                    "source_version_id": source_version,
                    "key": payload.key,
                    "kind": payload.kind,
                    "value": payload.value,
                    "content_digest": content_digest,
                },
            )
            fact_id, document_id = artifact_id, None
        else:
            await self._session.execute(
                text(
                    "INSERT INTO public.knowledge_documents "
                    "(id, tenant_id, source_id, source_version_id, category, title, "
                    "document_text, locator, content_digest) VALUES (:id, :tenant_id, "
                    ":source_id, :source_version_id, :category, :title, :document_text, "
                    ":locator, :content_digest)"
                ).bindparams(bindparam("locator", type_=JSONB)),
                {
                    "id": artifact_id,
                    "tenant_id": self._context.tenant_id,
                    "source_id": proposal.source_id,
                    "source_version_id": source_version,
                    "category": payload.category,
                    "title": payload.title,
                    "document_text": payload.text,
                    "locator": payload.locator,
                    "content_digest": content_digest,
                },
            )
            fact_id, document_id = None, artifact_id
        position = await self._session.scalar(
            text(
                "SELECT coalesce(max(position), -1) + 1 "
                "FROM public.knowledge_version_members WHERE tenant_id = :tenant_id "
                "AND knowledge_version_id = :version_id"
            ),
            {"tenant_id": self._context.tenant_id, "version_id": draft_version_id},
        )
        await self._session.execute(
            text(
                "INSERT INTO public.knowledge_version_members "
                "(id, tenant_id, knowledge_version_id, structured_fact_id, "
                "document_id, position) VALUES (:id, :tenant_id, :version_id, "
                ":fact_id, :document_id, :position)"
            ),
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "version_id": draft_version_id,
                "fact_id": fact_id,
                "document_id": document_id,
                "position": position,
            },
        )

    async def _approved_source_version(self, proposal: KnowledgeProposal) -> UUID:
        ingestion = (
            (
                await self._session.execute(
                    text(
                        "SELECT content_digest FROM public.knowledge_ingestions "
                        "WHERE tenant_id = :tenant_id AND id = :ingestion_id "
                        "AND state = 'SUCCEEDED'"
                    ),
                    {
                        "tenant_id": self._context.tenant_id,
                        "ingestion_id": proposal.ingestion_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if ingestion is None:
            raise _review_error("knowledge_ingestion_not_complete", 409)
        existing = await self._session.scalar(
            text(
                "SELECT id FROM public.knowledge_source_versions "
                "WHERE tenant_id = :tenant_id AND source_id = :source_id "
                "AND content_digest = :content_digest"
            ),
            {
                "tenant_id": self._context.tenant_id,
                "source_id": proposal.source_id,
                "content_digest": ingestion["content_digest"],
            },
        )
        if existing is not None:
            return cast(UUID, existing)
        version_id = new_uuid7()
        await self._session.execute(
            text(
                "INSERT INTO public.knowledge_source_versions "
                "(id, tenant_id, source_id, version_number, authority, content_digest, "
                "verified_at, approved_by_admin_id, locator) SELECT :id, source.tenant_id, "
                "source.id, coalesce(max(version.version_number), 0) + 1, source.authority, "
                ":content_digest, now(), :admin_id, :locator "
                "FROM public.knowledge_sources AS source LEFT JOIN "
                "public.knowledge_source_versions AS version "
                "ON version.tenant_id = source.tenant_id AND version.source_id = source.id "
                "WHERE source.tenant_id = :tenant_id AND source.id = :source_id "
                "GROUP BY source.tenant_id, source.id, source.authority"
            ).bindparams(bindparam("locator", type_=JSONB)),
            {
                "id": version_id,
                "tenant_id": self._context.tenant_id,
                "source_id": proposal.source_id,
                "content_digest": ingestion["content_digest"],
                "admin_id": self._context.actor_id,
                "locator": {"ingestion_id": str(proposal.ingestion_id)},
            },
        )
        return version_id

    async def _draft_version(self, proposal: KnowledgeProposal) -> UUID:
        existing = await self._session.scalar(
            text(
                "SELECT draft_version_id FROM public.knowledge_source_diffs "
                "WHERE tenant_id = :tenant_id AND ingestion_id = :ingestion_id"
            ),
            {
                "tenant_id": self._context.tenant_id,
                "ingestion_id": proposal.ingestion_id,
            },
        )
        if existing is not None:
            return cast(UUID, existing)
        ingestion = (
            (
                await self._session.execute(
                    text(
                        "SELECT content_digest, proposed_artifact_count "
                        "FROM public.knowledge_ingestions WHERE tenant_id = :tenant_id "
                        "AND id = :ingestion_id"
                    ),
                    {
                        "tenant_id": self._context.tenant_id,
                        "ingestion_id": proposal.ingestion_id,
                    },
                )
            )
            .mappings()
            .one()
        )
        created = await self._session.scalar(
            text(
                "SELECT agents_factory_private.record_knowledge_source_diff("
                ":id, :tenant_id, :source_id, :ingestion_id, :digest, :summary)"
            ).bindparams(bindparam("summary", type_=JSONB)),
            {
                "id": new_uuid7(),
                "tenant_id": self._context.tenant_id,
                "source_id": proposal.source_id,
                "ingestion_id": proposal.ingestion_id,
                "digest": ingestion["content_digest"],
                "summary": {
                    "proposed_artifact_count": ingestion["proposed_artifact_count"]
                },
            },
        )
        if created is None:
            raise _review_error("knowledge_source_unchanged", 409)
        return cast(UUID, created)

    async def _resolve_conflicts(self, *, proposal_id: UUID, resolution: str) -> None:
        await self._session.execute(
            text(
                "UPDATE public.knowledge_conflicts SET state = 'RESOLVED', "
                "resolution = :resolution, resolved_by_admin_id = :admin_id, "
                "resolved_at = now() WHERE tenant_id = :tenant_id "
                "AND proposal_id = :proposal_id AND state = 'OPEN'"
            ),
            {
                "resolution": resolution,
                "admin_id": self._context.actor_id,
                "tenant_id": self._context.tenant_id,
                "proposal_id": proposal_id,
            },
        )


def _review_error(code: str, status: int) -> DomainError:
    return DomainError(
        type=f"https://agents-factory.dev/problems/{code.replace('_', '-')}",
        title="Knowledge Proposal Review Rejected",
        status=status,
        detail="The proposal review could not be applied to this tenant revision.",
        code=code,
    )
