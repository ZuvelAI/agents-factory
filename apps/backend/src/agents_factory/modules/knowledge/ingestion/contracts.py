from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agents_factory.modules.knowledge.models import (
    CriticalFactKind,
    KnowledgeAuthority,
    KnowledgeDocumentCategory,
    KnowledgeSourceType,
    Sha256Digest,
)


MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 2_000_000


class IngestionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceDescriptor(IngestionModel):
    tenant_id: UUID
    source_id: UUID
    source_type: KnowledgeSourceType
    authority: KnowledgeAuthority
    configuration: dict[str, object]


class FetchedSource(IngestionModel):
    descriptor: SourceDescriptor
    content: bytes = Field(max_length=MAX_SOURCE_BYTES)
    media_type: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=300)
    locator: dict[str, object]
    content_digest: Sha256Digest


class ExtractedBlock(IngestionModel):
    kind: Literal["TEXT", "TABLE"]
    text: str = Field(min_length=1, max_length=MAX_EXTRACTED_CHARACTERS)
    locator: dict[str, object]
    rows: tuple[tuple[str, ...], ...] = ()


class ExtractedDocument(IngestionModel):
    title: str = Field(min_length=1, max_length=300)
    blocks: tuple[ExtractedBlock, ...]
    source_digest: Sha256Digest


class ProposedFact(IngestionModel):
    source_id: UUID
    authority: KnowledgeAuthority
    key: str = Field(pattern=r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
    kind: CriticalFactKind
    value: dict[str, object]
    locator: dict[str, object]
    content_digest: Sha256Digest


class ProposedDocument(IngestionModel):
    source_id: UUID
    authority: KnowledgeAuthority
    category: KnowledgeDocumentCategory
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=MAX_EXTRACTED_CHARACTERS)
    locator: dict[str, object]
    content_digest: Sha256Digest


class NormalizedKnowledge(IngestionModel):
    source_digest: Sha256Digest
    facts: tuple[ProposedFact, ...] = ()
    documents: tuple[ProposedDocument, ...] = ()


class IngestionRejected(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SourceFetcher(Protocol):
    async def fetch(self, source: SourceDescriptor) -> FetchedSource: ...


class DocumentExtractor(Protocol):
    def extract(self, fetched: FetchedSource) -> ExtractedDocument: ...


class PrivateSourceStore(Protocol):
    async def put(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        digest: str,
        content: bytes,
        media_type: str,
    ) -> str: ...


class DraftArtifactSink(Protocol):
    async def persist(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        storage_path: str,
        normalized: NormalizedKnowledge,
    ) -> None: ...


class DriveFileClient(Protocol):
    async def download(self, file_id: str) -> tuple[bytes, Mapping[str, object]]: ...


class UploadedSourceReader(Protocol):
    async def read_upload(
        self, *, tenant_id: UUID, source_id: UUID, upload_key: str
    ) -> tuple[bytes, Mapping[str, object]]: ...
