from __future__ import annotations

import hashlib


def pseudonymize(tenant_id: str, subject_ref: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{subject_ref}".encode()).hexdigest()
    return f"deleted:{digest[:32]}"


def direct_identifier_free_metrics() -> frozenset[str]:
    return frozenset({"count", "duration_ms", "tokens", "cost_amount", "currency"})
