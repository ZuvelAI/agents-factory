from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.knowledge.models import (
    KnowledgeIngestion,
    KnowledgeSource,
    KnowledgeVersion,
    knowledge_digest,
)
from agents_factory.modules.knowledge.proposals import KnowledgeProposal


class WorkspaceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KnowledgeSourceOverview(WorkspaceModel):
    source: KnowledgeSource
    latest_ingestion: KnowledgeIngestion | None


class KnowledgeConflictRecord(WorkspaceModel):
    id: UUID
    proposal_id: UUID
    source_id: UUID
    fact_key: str | None
    critical: bool
    proposed_authority: str
    existing_authority: str
    state: Literal["OPEN", "RESOLVED"]
    resolution: Literal["APPROVED", "EDITED", "REJECTED"] | None
    details: dict[str, object]
    created_at: datetime


class KnowledgeSourceDiffRecord(WorkspaceModel):
    id: UUID
    source_id: UUID
    ingestion_id: UUID
    draft_version_id: UUID
    previous_digest: str | None = Field(default=None, pattern=r"[0-9a-f]{64}")
    current_digest: str = Field(pattern=r"[0-9a-f]{64}")
    state: Literal["DETECTED", "REVIEWED"]
    summary: dict[str, object]
    created_at: datetime


class KnowledgeVersionOverview(WorkspaceModel):
    version: KnowledgeVersion
    structured_fact_count: int = Field(ge=0)
    document_count: int = Field(ge=0)
    candidate_digest: str | None = Field(default=None, pattern=r"[0-9a-f]{64}")
    v0_evaluation: Literal["NOT_RUN", "PASSED", "FAILED"]
    v0_passed_cases: int = Field(ge=0)
    v0_failed_cases: int = Field(ge=0)


class KnowledgeWorkspace(WorkspaceModel):
    sources: tuple[KnowledgeSourceOverview, ...]
    proposals: tuple[KnowledgeProposal, ...]
    conflicts: tuple[KnowledgeConflictRecord, ...]
    diffs: tuple[KnowledgeSourceDiffRecord, ...]
    versions: tuple[KnowledgeVersionOverview, ...]
    production_blocker_code: Literal["production_quality_gate_required"] = (
        "production_quality_gate_required"
    )
    production_blocker: str = "Production requires the full Task 45 Quality Gate for the exact Knowledge digest."


class KnowledgeWorkspaceService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self._session = session
        self._context = context

    async def read(self) -> KnowledgeWorkspace:
        await set_tenant_context(self._session, self._context.tenant_id)
        return KnowledgeWorkspace(
            sources=await self._sources(),
            proposals=await self._proposals(),
            conflicts=await self._conflicts(),
            diffs=await self._diffs(),
            versions=await self._versions(),
        )

    async def _sources(self) -> tuple[KnowledgeSourceOverview, ...]:
        source_rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id,tenant_id,name,source_type,authority,configuration,created_at "
                        "FROM public.knowledge_sources WHERE tenant_id=:tenant "
                        "ORDER BY created_at DESC,id LIMIT 200"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        ingestion_rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT DISTINCT ON (source_id) id,tenant_id,source_id,state,"
                        "content_digest,storage_path,proposed_artifact_count,error_code,"
                        "created_at,updated_at,completed_at FROM public.knowledge_ingestions "
                        "WHERE tenant_id=:tenant ORDER BY source_id,created_at DESC,id DESC"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        latest = {
            row["source_id"]: KnowledgeIngestion.from_mapping(row)
            for row in ingestion_rows
        }
        return tuple(
            KnowledgeSourceOverview(
                source=KnowledgeSource.from_mapping(row),
                latest_ingestion=latest.get(row["id"]),
            )
            for row in source_rows
        )

    async def _proposals(self) -> tuple[KnowledgeProposal, ...]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id,tenant_id,ingestion_artifact_id,ingestion_id,source_id,"
                        "revision,artifact_type,state,proposed_payload,decision_payload,"
                        "proposed_by,model_metadata,content_digest,decided_by_admin_id "
                        "FROM public.knowledge_proposals WHERE tenant_id=:tenant "
                        "ORDER BY (state='PROPOSED') DESC,created_at,id LIMIT 300"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(KnowledgeProposal.from_mapping(row) for row in rows)

    async def _conflicts(self) -> tuple[KnowledgeConflictRecord, ...]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT conflict.id,conflict.proposal_id,proposal.source_id,"
                        "conflict.fact_key,conflict.critical,conflict.proposed_authority,"
                        "conflict.existing_authority,conflict.state,conflict.resolution,"
                        "conflict.details,conflict.created_at FROM public.knowledge_conflicts "
                        "AS conflict JOIN public.knowledge_proposals AS proposal "
                        "ON proposal.tenant_id=conflict.tenant_id "
                        "AND proposal.id=conflict.proposal_id "
                        "WHERE conflict.tenant_id=:tenant "
                        "ORDER BY (conflict.state='OPEN') DESC,conflict.critical DESC,"
                        "conflict.created_at DESC LIMIT 300"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(KnowledgeConflictRecord.model_validate(dict(row)) for row in rows)

    async def _diffs(self) -> tuple[KnowledgeSourceDiffRecord, ...]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id,source_id,ingestion_id,draft_version_id,previous_digest,"
                        "current_digest,state,summary,created_at "
                        "FROM public.knowledge_source_diffs WHERE tenant_id=:tenant "
                        "ORDER BY created_at DESC,id LIMIT 200"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(
            KnowledgeSourceDiffRecord.model_validate(dict(row)) for row in rows
        )

    async def _versions(self) -> tuple[KnowledgeVersionOverview, ...]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT version.id,version.tenant_id,version.name,"
                        "version.version_number,version.state,version.digest,"
                        "version.based_on_version_id,version.created_at,version.updated_at,"
                        "count(member.structured_fact_id) AS fact_count,"
                        "count(member.document_id) AS document_count "
                        "FROM public.knowledge_versions AS version LEFT JOIN "
                        "public.knowledge_version_members AS member "
                        "ON member.tenant_id=version.tenant_id "
                        "AND member.knowledge_version_id=version.id "
                        "WHERE version.tenant_id=:tenant GROUP BY version.id "
                        "ORDER BY version.version_number DESC LIMIT 100"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        evidence_rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT DISTINCT ON (knowledge_version_id) knowledge_version_id,"
                        "passed,passed_cases,failed_cases FROM public.knowledge_eval_evidence "
                        "WHERE tenant_id=:tenant ORDER BY knowledge_version_id,created_at DESC"
                    ),
                    {"tenant": self._context.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        evidence = {row["knowledge_version_id"]: row for row in evidence_rows}
        overviews: list[KnowledgeVersionOverview] = []
        for row in rows:
            version = KnowledgeVersion.model_validate(
                {field: row[field] for field in KnowledgeVersion.model_fields}
            )
            digests = await self._member_digests(version.id)
            candidate_digest = knowledge_digest(digests) if digests else None
            result = evidence.get(version.id)
            overviews.append(
                KnowledgeVersionOverview(
                    version=version,
                    structured_fact_count=row["fact_count"],
                    document_count=row["document_count"],
                    candidate_digest=candidate_digest,
                    v0_evaluation=(
                        "NOT_RUN"
                        if result is None
                        else "PASSED"
                        if result["passed"] and result["failed_cases"] == 0
                        else "FAILED"
                    ),
                    v0_passed_cases=0 if result is None else result["passed_cases"],
                    v0_failed_cases=0 if result is None else result["failed_cases"],
                )
            )
        return tuple(overviews)

    async def _member_digests(self, version_id: UUID) -> tuple[str, ...]:
        result = await self._session.execute(
            text(
                "SELECT coalesce(fact.content_digest,document.content_digest) "
                "FROM public.knowledge_version_members AS member LEFT JOIN "
                "public.structured_facts AS fact ON fact.tenant_id=member.tenant_id "
                "AND fact.id=member.structured_fact_id LEFT JOIN "
                "public.knowledge_documents AS document "
                "ON document.tenant_id=member.tenant_id "
                "AND document.id=member.document_id WHERE member.tenant_id=:tenant "
                "AND member.knowledge_version_id=:version ORDER BY member.position"
            ),
            {"tenant": self._context.tenant_id, "version": version_id},
        )
        return tuple(result.scalars())
