from __future__ import annotations

from uuid import uuid4

from agents_factory.modules.knowledge.change_detection import detect_source_change


def test_source_diff_is_stable_and_unchanged_digest_is_not_a_change() -> None:
    source_id = uuid4()
    unchanged = detect_source_change(
        source_id=source_id,
        previous_digest="a" * 64,
        current_digest="a" * 64,
        previous_artifact_digests=("1" * 64,),
        current_artifact_digests=("1" * 64,),
    )
    changed = detect_source_change(
        source_id=source_id,
        previous_digest="a" * 64,
        current_digest="b" * 64,
        previous_artifact_digests=("1" * 64, "2" * 64),
        current_artifact_digests=("2" * 64, "3" * 64),
    )

    assert not unchanged.changed
    assert changed.changed
    assert changed.added == ("3" * 64,)
    assert changed.removed == ("1" * 64,)
    assert changed.unchanged == ("2" * 64,)
