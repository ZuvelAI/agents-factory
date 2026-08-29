from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.engine import RowMapping


KnowledgeAuthority = Literal["AUTHORITATIVE", "SECONDARY", "REFERENCE"]
KnowledgeSourceType = Literal[
    "WEBSITE",
    "PDF",
    "DOCX",
    "GOOGLE_DRIVE",
    "SPREADSHEET",
    "MANUAL",
]
CriticalFactKind = Literal[
    "BUSINESS_HOURS",
    "LOCATION",
    "SERVICE",
    "PRICE",
    "CONTACT",
    "BOOKING_RULE",
    "APPROVAL_CONTACT",
]
KnowledgeDocumentCategory = Literal[
    "POLICY",
    "MANUAL",
    "FAQ",
    "CATALOG_DESCRIPTION",
    "PROCEDURE",
    "DOCUMENTATION",
]
KnowledgeVersionState = Literal["DRAFT", "TEST", "PRODUCTION"]


def _validate_digest(value: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("digest must be lowercase SHA-256")
    return value


Sha256Digest = Annotated[str, AfterValidator(_validate_digest)]


class FrozenKnowledgeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KnowledgeProvenance(FrozenKnowledgeModel):
    source_id: UUID
    source_version_id: UUID
    authority: KnowledgeAuthority
    verified_at: datetime
    approved_by_admin_id: UUID
    content_digest: Sha256Digest


class StructuredFactDraft(FrozenKnowledgeModel):
    key: str = Field(pattern=r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
    kind: CriticalFactKind
    value: dict[str, object]
    provenance: KnowledgeProvenance


class KnowledgeDocumentDraft(FrozenKnowledgeModel):
    category: KnowledgeDocumentCategory
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=2_000_000)
    locator: dict[str, object]
    provenance: KnowledgeProvenance


class AuthorityCandidate(FrozenKnowledgeModel):
    id: UUID
    key: str
    value: dict[str, object]
    provenance: KnowledgeProvenance


class AuthorityResolution(FrozenKnowledgeModel):
    selected: AuthorityCandidate | None
    conflicting: tuple[AuthorityCandidate, ...]
    considered: tuple[AuthorityCandidate, ...]

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicting)


_AUTHORITY_RANK: dict[KnowledgeAuthority, int] = {
    "AUTHORITATIVE": 3,
    "SECONDARY": 2,
    "REFERENCE": 1,
}


def resolve_authority(
    candidates: tuple[AuthorityCandidate, ...],
) -> AuthorityResolution:
    """Resolve one key explicitly; conflicting candidates remain visible."""
    if not candidates:
        return AuthorityResolution(selected=None, conflicting=(), considered=())
    keys = {candidate.key for candidate in candidates}
    if len(keys) != 1:
        raise ValueError("authority resolution requires exactly one fact key")

    top_rank = max(
        _AUTHORITY_RANK[candidate.provenance.authority] for candidate in candidates
    )
    top = tuple(
        candidate
        for candidate in candidates
        if _AUTHORITY_RANK[candidate.provenance.authority] == top_rank
    )
    top_values = {_canonical_json(candidate.value) for candidate in top}
    if len(top_values) > 1:
        return AuthorityResolution(
            selected=None,
            conflicting=candidates,
            considered=candidates,
        )

    selected = min(top, key=lambda candidate: str(candidate.id))
    conflicting = tuple(
        candidate
        for candidate in candidates
        if _canonical_json(candidate.value) != _canonical_json(selected.value)
    )
    return AuthorityResolution(
        selected=selected,
        conflicting=conflicting,
        considered=candidates,
    )


def knowledge_digest(member_digests: tuple[str, ...]) -> Sha256Digest:
    if not member_digests:
        raise ValueError("a Knowledge version requires at least one member")
    validated = tuple(_validate_digest(value) for value in member_digests)
    payload = _canonical_json({"schema_version": "1.0", "members": sorted(validated)})
    return _validate_digest(sha256(payload.encode("utf-8")).hexdigest())


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class KnowledgeSource(FrozenKnowledgeModel):
    id: UUID
    tenant_id: UUID
    name: str
    source_type: KnowledgeSourceType
    authority: KnowledgeAuthority
    configuration: dict[str, object]
    created_at: datetime

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls.model_validate(dict(row))


class KnowledgeSourceVersion(FrozenKnowledgeModel):
    id: UUID
    tenant_id: UUID
    source_id: UUID
    version_number: int = Field(ge=1)
    authority: KnowledgeAuthority
    content_digest: Sha256Digest
    verified_at: datetime
    approved_by_admin_id: UUID
    locator: dict[str, object]
    created_at: datetime

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls.model_validate(dict(row))


class StructuredFact(FrozenKnowledgeModel):
    id: UUID
    tenant_id: UUID
    key: str
    kind: CriticalFactKind
    value: dict[str, object]
    provenance: KnowledgeProvenance
    created_at: datetime


class KnowledgeDocument(FrozenKnowledgeModel):
    id: UUID
    tenant_id: UUID
    category: KnowledgeDocumentCategory
    title: str
    text: str
    locator: dict[str, object]
    provenance: KnowledgeProvenance
    created_at: datetime


class KnowledgeVersion(FrozenKnowledgeModel):
    id: UUID
    tenant_id: UUID
    name: str
    version_number: int = Field(ge=1)
    state: KnowledgeVersionState
    digest: Sha256Digest | None
    based_on_version_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls.model_validate(dict(row))


class KnowledgeVersionMember(FrozenKnowledgeModel):
    id: UUID
    tenant_id: UUID
    knowledge_version_id: UUID
    structured_fact_id: UUID | None = None
    document_id: UUID | None = None
    position: int = Field(ge=0)
    created_at: datetime

    @model_validator(mode="after")
    def exactly_one_artifact(self) -> Self:
        if (self.structured_fact_id is None) == (self.document_id is None):
            raise ValueError("a member must reference exactly one Knowledge artifact")
        return self


class KnowledgeIngestion(FrozenKnowledgeModel):
    id: UUID
    tenant_id: UUID
    source_id: UUID
    state: Literal["PENDING", "PROCESSING", "SUCCEEDED", "FAILED"]
    content_digest: Sha256Digest | None
    storage_path: str | None
    proposed_artifact_count: int = Field(ge=0)
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_mapping(cls, row: RowMapping) -> Self:
        return cls.model_validate(dict(row))
