from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agents_factory.modules.knowledge.models import (
    KnowledgeAuthority,
    KnowledgeDocumentCategory,
    KnowledgeSourceType,
    StructuredFactDraft,
)
from agents_factory.modules.knowledge.proposals import ProposalDecision


class KnowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateKnowledgeSourceRequest(KnowledgeRequest):
    name: str = Field(min_length=1, max_length=300)
    source_type: KnowledgeSourceType
    authority: KnowledgeAuthority
    configuration: dict[str, object] = Field(default_factory=dict)


class AppendSourceVersionRequest(KnowledgeRequest):
    version_number: int = Field(ge=1)
    content_digest: str = Field(pattern=r"[0-9a-f]{64}")
    verified_at: datetime
    locator: dict[str, object] = Field(default_factory=dict)


class AddStructuredFactRequest(KnowledgeRequest):
    fact: StructuredFactDraft


class AddKnowledgeDocumentRequest(KnowledgeRequest):
    category: KnowledgeDocumentCategory
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=2_000_000)
    locator: dict[str, object] = Field(default_factory=dict)
    source_id: UUID
    source_version_id: UUID
    content_digest: str = Field(pattern=r"[0-9a-f]{64}")


class CreateKnowledgeVersionRequest(KnowledgeRequest):
    name: str = Field(min_length=1, max_length=300)
    based_on_version_id: UUID | None = None


class AddKnowledgeMembersRequest(KnowledgeRequest):
    structured_fact_ids: tuple[UUID, ...] = ()
    document_ids: tuple[UUID, ...] = ()


class EmbeddingJobResponse(KnowledgeRequest):
    job_id: UUID
    knowledge_version_id: UUID


class KnowledgeEvalEvidenceRequest(KnowledgeRequest):
    id: UUID
    knowledge_digest: str = Field(pattern=r"[0-9a-f]{64}")
    suite_digest: str = Field(pattern=r"[0-9a-f]{64}")
    runner_version: str = Field(min_length=1, max_length=100)
    passed: bool
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)


class ReviewKnowledgeProposalRequest(KnowledgeRequest):
    revision: int = Field(ge=1)
    decision: ProposalDecision
    edited_payload: dict[str, object] | None = None
