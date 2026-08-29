from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agents_factory.common.errors import DomainError
from agents_factory.modules.knowledge.models import KnowledgeVersion, knowledge_digest
from agents_factory.modules.knowledge.publishing import KnowledgeEvalEvidence
from agents_factory.modules.knowledge.service import KnowledgeService


class _PublishingRepository:
    def __init__(self, version: KnowledgeVersion, member_digest: str) -> None:
        self.version = version
        self.member_digest = member_digest
        self.evidence_recorded = False

    async def get_version(self, version_id: object) -> KnowledgeVersion | None:
        return self.version if version_id == self.version.id else None

    async def has_complete_document_embeddings(self, version_id: object) -> bool:
        return version_id == self.version.id

    async def member_digests(self, version_id: object) -> tuple[str, ...]:
        return (self.member_digest,) if version_id == self.version.id else ()

    async def has_open_critical_conflicts(self, version_id: object) -> bool:
        return False

    async def record_eval_evidence(self, **values: object) -> None:
        self.evidence_recorded = bool(values)

    async def promote_to_test(
        self, *, version_id: object, digest: str
    ) -> KnowledgeVersion | None:
        if version_id != self.version.id:
            return None
        self.version = self.version.model_copy(
            update={"state": "TEST", "digest": digest}
        )
        return self.version

    async def audit(self, **values: object) -> None:
        _ = values


@pytest.mark.asyncio
async def test_test_publication_requires_exact_digest_eval_evidence() -> None:
    member_digest = "a" * 64
    version = KnowledgeVersion(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Candidate",
        version_number=1,
        state="DRAFT",
        digest=None,
        based_on_version_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    repository = _PublishingRepository(version, member_digest)
    service = KnowledgeService(repository)  # type: ignore[arg-type]
    exact_digest = knowledge_digest((member_digest,))

    published = await service.promote_to_test(
        version.id,
        evidence=KnowledgeEvalEvidence(
            id=uuid4(),
            knowledge_digest=exact_digest,
            suite_digest="b" * 64,
            runner_version="0.1.0",
            passed=True,
            passed_cases=2,
            failed_cases=0,
        ),
    )

    assert published.state == "TEST"
    assert published.digest == exact_digest
    assert repository.evidence_recorded

    with pytest.raises(DomainError, match="Quality Gate") as blocked:
        await service.publish_production(version.id)
    assert blocked.value.code == "production_quality_gate_required"
