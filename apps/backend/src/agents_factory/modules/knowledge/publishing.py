from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agents_factory.common.errors import DomainError


@dataclass(frozen=True, slots=True)
class KnowledgeEvalEvidence:
    id: UUID
    knowledge_digest: str
    suite_digest: str
    runner_version: str
    passed: bool
    passed_cases: int
    failed_cases: int

    def __post_init__(self) -> None:
        for digest in (self.knowledge_digest, self.suite_digest):
            if len(digest) != 64 or any(
                value not in "0123456789abcdef" for value in digest
            ):
                raise ValueError(
                    "Knowledge evidence requires lowercase SHA-256 digests"
                )
        if (
            not self.runner_version.strip()
            or self.passed_cases < 0
            or self.failed_cases < 0
        ):
            raise ValueError("Knowledge evidence metadata is invalid")

    def matches(self, digest: str) -> bool:
        return (
            self.passed
            and self.failed_cases == 0
            and self.passed_cases > 0
            and self.knowledge_digest == digest
        )


class KnowledgeProductionQualityGate(Protocol):
    async def evaluate(self, *, knowledge_digest: str) -> bool: ...


class FailClosedKnowledgeProductionQualityGate:
    """Task 45 replaces this boundary with exact-digest persisted evidence."""

    async def evaluate(self, *, knowledge_digest: str) -> bool:
        _ = knowledge_digest
        return False


async def require_production_gate(
    *,
    knowledge_digest: str,
    gate: KnowledgeProductionQualityGate,
) -> None:
    if not await gate.evaluate(knowledge_digest=knowledge_digest):
        raise DomainError(
            type="https://agents-factory.dev/problems/quality-gate-required",
            title="Production Quality Gate Required",
            status=409,
            detail=(
                "Knowledge Production publication is blocked until the full "
                "exact-digest Quality Gate is available."
            ),
            code="production_quality_gate_required",
        )
