from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agents_factory.modules.knowledge.models import KnowledgeAuthority


_AUTHORITY_RANK: dict[KnowledgeAuthority, int] = {
    "AUTHORITATIVE": 3,
    "SECONDARY": 2,
    "REFERENCE": 1,
}
ConflictReason = Literal[
    "HIGHER_AUTHORITY_EXISTS",
    "EQUAL_AUTHORITY_DISAGREEMENT",
    "LOWER_AUTHORITY_DISAGREEMENT",
]


class ConflictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExistingFact(ConflictModel):
    id: UUID
    key: str
    value: dict[str, object]
    authority: KnowledgeAuthority


class ProposedFactValue(ConflictModel):
    proposal_id: UUID
    key: str
    value: dict[str, object]
    authority: KnowledgeAuthority


class KnowledgeConflictDraft(ConflictModel):
    proposal_id: UUID
    fact_key: str
    critical: bool
    proposed_authority: KnowledgeAuthority
    existing_authority: KnowledgeAuthority
    existing_fact_id: UUID
    reason: ConflictReason


def detect_fact_conflicts(
    proposed: ProposedFactValue,
    existing: tuple[ExistingFact, ...],
) -> tuple[KnowledgeConflictDraft, ...]:
    conflicts: list[KnowledgeConflictDraft] = []
    proposed_value = _canonical(proposed.value)
    for fact in existing:
        if fact.key != proposed.key or _canonical(fact.value) == proposed_value:
            continue
        proposed_rank = _AUTHORITY_RANK[proposed.authority]
        existing_rank = _AUTHORITY_RANK[fact.authority]
        if existing_rank > proposed_rank:
            reason: ConflictReason = "HIGHER_AUTHORITY_EXISTS"
        elif existing_rank == proposed_rank:
            reason = "EQUAL_AUTHORITY_DISAGREEMENT"
        else:
            reason = "LOWER_AUTHORITY_DISAGREEMENT"
        conflicts.append(
            KnowledgeConflictDraft(
                proposal_id=proposed.proposal_id,
                fact_key=proposed.key,
                critical=existing_rank >= proposed_rank,
                proposed_authority=proposed.authority,
                existing_authority=fact.authority,
                existing_fact_id=fact.id,
                reason=reason,
            )
        )
    return tuple(conflicts)


def _canonical(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
