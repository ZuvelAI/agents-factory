from __future__ import annotations

from uuid import uuid4

from agents_factory.modules.knowledge.conflicts import (
    ExistingFact,
    ProposedFactValue,
    detect_fact_conflicts,
)


def test_conflict_severity_follows_explicit_authority_order() -> None:
    proposed = ProposedFactValue(
        proposal_id=uuid4(),
        key="operations.business_hours.main",
        value={"closes": "18:00"},
        authority="SECONDARY",
    )
    conflicts = detect_fact_conflicts(
        proposed,
        (
            ExistingFact(
                id=uuid4(),
                key=proposed.key,
                value={"closes": "17:00"},
                authority="AUTHORITATIVE",
            ),
            ExistingFact(
                id=uuid4(),
                key=proposed.key,
                value={"closes": "16:00"},
                authority="SECONDARY",
            ),
            ExistingFact(
                id=uuid4(),
                key=proposed.key,
                value={"closes": "15:00"},
                authority="REFERENCE",
            ),
        ),
    )

    assert [conflict.reason for conflict in conflicts] == [
        "HIGHER_AUTHORITY_EXISTS",
        "EQUAL_AUTHORITY_DISAGREEMENT",
        "LOWER_AUTHORITY_DISAGREEMENT",
    ]
    assert [conflict.critical for conflict in conflicts] == [True, True, False]


def test_identical_values_do_not_create_a_conflict() -> None:
    key = "catalog.price.standard"
    assert (
        detect_fact_conflicts(
            ProposedFactValue(
                proposal_id=uuid4(),
                key=key,
                value={"amount": 25_000, "currency": "COP"},
                authority="REFERENCE",
            ),
            (
                ExistingFact(
                    id=uuid4(),
                    key=key,
                    value={"currency": "COP", "amount": 25_000},
                    authority="AUTHORITATIVE",
                ),
            ),
        )
        == ()
    )
