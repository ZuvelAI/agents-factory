from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceDiff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: UUID
    previous_digest: str | None = Field(default=None, pattern=r"[0-9a-f]{64}")
    current_digest: str = Field(pattern=r"[0-9a-f]{64}")
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.previous_digest != self.current_digest


def detect_source_change(
    *,
    source_id: UUID,
    previous_digest: str | None,
    current_digest: str,
    previous_artifact_digests: tuple[str, ...] = (),
    current_artifact_digests: tuple[str, ...] = (),
) -> SourceDiff:
    previous = set(previous_artifact_digests)
    current = set(current_artifact_digests)
    return SourceDiff(
        source_id=source_id,
        previous_digest=previous_digest,
        current_digest=current_digest,
        added=tuple(sorted(current - previous)),
        removed=tuple(sorted(previous - current)),
        unchanged=tuple(sorted(previous & current)),
    )
