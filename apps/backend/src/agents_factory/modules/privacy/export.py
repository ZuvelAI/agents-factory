from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.modules.privacy.models import PrivacyExportManifest


async def build_export_manifest(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    subject_type: str,
    subject_ref: str,
) -> PrivacyExportManifest:
    counts: dict[str, int] = {}
    for table in ("conversations", "messages", "actions", "cases", "media_evidence"):
        counts[table] = int(
            await session.scalar(
                text(f"SELECT count(*) FROM public.{table} WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )
            or 0
        )
    digest = hashlib.sha256(f"{tenant_id}:{subject_ref}".encode()).hexdigest()
    checksums = {
        "inventory": hashlib.sha256(
            json.dumps(counts, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    }
    return PrivacyExportManifest(
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_ref_digest=digest,
        counts=counts,
        checksums=checksums,
        generated_at=datetime.now(UTC),
    )
