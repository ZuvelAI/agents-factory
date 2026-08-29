from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from agents_factory.modules.knowledge.models import (
    AuthorityCandidate,
    KnowledgeDocumentDraft,
    KnowledgeProvenance,
    StructuredFactDraft,
    resolve_authority,
)


SOURCE_ID = UUID("10000000-0000-0000-0000-000000000001")
SOURCE_VERSION_ID = UUID("20000000-0000-0000-0000-000000000001")
ADMIN_ID = UUID("30000000-0000-0000-0000-000000000001")
VERIFIED_AT = datetime(2026, 8, 29, tzinfo=UTC)


def provenance(*, authority: str = "AUTHORITATIVE") -> KnowledgeProvenance:
    return KnowledgeProvenance(
        source_id=SOURCE_ID,
        source_version_id=SOURCE_VERSION_ID,
        authority=authority,
        verified_at=VERIFIED_AT,
        approved_by_admin_id=ADMIN_ID,
        content_digest="a" * 64,
    )


def test_critical_operational_knowledge_is_structured_not_vector_only() -> None:
    for kind in (
        "BUSINESS_HOURS",
        "LOCATION",
        "SERVICE",
        "PRICE",
        "CONTACT",
        "BOOKING_RULE",
        "APPROVAL_CONTACT",
    ):
        fact = StructuredFactDraft(
            key=f"operations.{kind.lower()}",
            kind=kind,
            value={"value": "configured"},
            provenance=provenance(),
        )
        assert fact.kind == kind

    with pytest.raises(ValidationError):
        KnowledgeDocumentDraft(
            category="BUSINESS_HOURS",
            title="Horario",
            text="Lunes a viernes",
            locator={"page": 1},
            provenance=provenance(),
        )


def test_provenance_is_complete_and_digest_validated() -> None:
    serialized = provenance().model_dump(mode="json")
    assert serialized == {
        "source_id": str(SOURCE_ID),
        "source_version_id": str(SOURCE_VERSION_ID),
        "authority": "AUTHORITATIVE",
        "verified_at": VERIFIED_AT.isoformat().replace("+00:00", "Z"),
        "approved_by_admin_id": str(ADMIN_ID),
        "content_digest": "a" * 64,
    }

    with pytest.raises(ValidationError):
        KnowledgeProvenance(
            source_id=SOURCE_ID,
            source_version_id=SOURCE_VERSION_ID,
            authority="AUTHORITATIVE",
            verified_at=VERIFIED_AT,
            approved_by_admin_id=ADMIN_ID,
            content_digest="not-a-digest",
        )


def test_higher_authority_wins_without_hiding_conflicting_candidates() -> None:
    result = resolve_authority(
        (
            AuthorityCandidate(
                id=UUID("40000000-0000-0000-0000-000000000001"),
                key="operations.price.standard",
                value={"amount": 90},
                provenance=provenance(authority="SECONDARY"),
            ),
            AuthorityCandidate(
                id=UUID("40000000-0000-0000-0000-000000000002"),
                key="operations.price.standard",
                value={"amount": 100},
                provenance=provenance(authority="AUTHORITATIVE"),
            ),
        )
    )

    assert result.selected is not None
    assert result.selected.value == {"amount": 100}
    assert result.has_conflict is True
    assert [candidate.value for candidate in result.conflicting] == [{"amount": 90}]


def test_equal_top_authority_conflict_is_unresolved() -> None:
    candidates = tuple(
        AuthorityCandidate(
            id=UUID(f"50000000-0000-0000-0000-00000000000{index}"),
            key="operations.business_hours.main",
            value={"opens": opens},
            provenance=provenance(),
        )
        for index, opens in ((1, "08:00"), (2, "09:00"))
    )

    result = resolve_authority(candidates)

    assert result.selected is None
    assert result.has_conflict is True
    assert result.conflicting == candidates
