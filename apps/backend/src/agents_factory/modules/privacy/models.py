from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PrivacyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PrivacyJobRequest(PrivacyModel):
    operation: Literal["DELETE", "EXPORT", "REVOKE_INTEGRATIONS"]
    subject_type: Literal["CONVERSATION", "CUSTOMER", "TENANT"]
    subject_ref: str = Field(min_length=1, max_length=300)
    idempotency_key: str = Field(min_length=16, max_length=200)
    legal_hold: bool = False

    @field_validator("subject_ref", "idempotency_key")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("privacy values must be trimmed")
        return value


class PrivacyJob(PrivacyModel):
    id: UUID
    operation: Literal["DELETE", "EXPORT", "REVOKE_INTEGRATIONS"]
    subject_type: Literal["CONVERSATION", "CUSTOMER", "TENANT"]
    subject_ref: str
    status: Literal["REQUESTED", "STARTED", "COMPLETED", "FAILED", "HELD"]
    legal_hold: bool
    result_manifest: dict[str, object]
    error_code: str | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class PrivacyExportManifest(PrivacyModel):
    schema_version: Literal[1] = 1
    tenant_id: UUID
    subject_type: str
    subject_ref_digest: str
    counts: dict[str, int]
    checksums: dict[str, str]
    generated_at: datetime
    includes_raw_content_in_logs: Literal[False] = False
