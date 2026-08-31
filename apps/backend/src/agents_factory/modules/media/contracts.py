from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agents_factory.common.context import TenantContext

MediaKind = Literal[
    "text", "audio", "image", "document", "location", "contacts", "video"
]
MediaState = Literal[
    "PROCESSING",
    "READY",
    "PENDING_PROVIDER",
    "HUMAN_REVIEW",
    "QUARANTINED",
    "FAILED",
    "DELETED",
]
MAX_BYTES = 20 * 1024 * 1024


class MediaError(ValueError):
    """Only code-owned reason codes; never provider diagnostics or file contents."""


class MediaModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MediaUsage(MediaModel):
    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    audio_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cost_basis: Literal["not_applicable", "unpriced", "configured_rate"] = (
        "not_applicable"
    )


class NormalizedMediaObservation(MediaModel):
    kind: MediaKind
    status: MediaState
    text: str = Field(default="", max_length=60000)
    fields: dict[str, object] = Field(default_factory=dict)
    evidence_id: UUID | None = None
    expires_at: datetime | None = None
    reason_code: str | None = None
    usage: MediaUsage = Field(default_factory=MediaUsage)
    # Media content is customer input, never authentication or business authority.
    trust: Literal["untrusted_customer_input"] = "untrusted_customer_input"
    identity_level_delta: Literal[0] = 0
    response_modality: Literal["text"] = "text"


class StoredMedia(MediaModel):
    id: UUID
    tenant_id: UUID
    whatsapp_account_id: UUID
    provider_media_id: str
    customer_ref: str
    first_message_id: UUID
    kind: MediaKind
    content_digest: str | None = None
    storage_key: str | None = None
    media_type: str | None = None
    byte_size: int = 0
    status: MediaState
    scan_status: Literal["PENDING", "CLEAN", "INFECTED", "UNAVAILABLE"] = "PENDING"
    observation: NormalizedMediaObservation | None = None
    created_at: datetime
    expires_at: datetime
    deleted_at: datetime | None = None


class BinaryMedia(MediaModel):
    content: bytes = Field(repr=False, max_length=MAX_BYTES)
    media_type: str


class MalwareScanner(Protocol):
    async def scan(
        self, content: bytes, *, media_type: str
    ) -> Literal["CLEAN", "INFECTED", "UNAVAILABLE"]: ...


class UnavailableScanner:
    async def scan(self, content: bytes, *, media_type: str) -> Literal["UNAVAILABLE"]:
        return "UNAVAILABLE"


class MediaNormalizer(Protocol):
    async def normalize(
        self,
        content: bytes,
        *,
        media_type: str,
        language: str,
        vocabulary: tuple[str, ...],
    ) -> NormalizedMediaObservation: ...


class MediaProcessor(Protocol):
    async def process(
        self, *, context: TenantContext, message_id: UUID
    ) -> NormalizedMediaObservation: ...
