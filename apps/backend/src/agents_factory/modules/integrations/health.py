from __future__ import annotations

from datetime import datetime

from agents_factory.modules.integrations.models import ConnectorHealth
from agents_factory.modules.integrations.oauth import ProviderFailure


def provider_failure_health(error: Exception, *, now: datetime) -> ConnectorHealth:
    code = error.code if isinstance(error, ProviderFailure) else "provider_unavailable"
    # Never persist provider exception messages, response bodies or request URLs.
    if code not in {
        "authorization_revoked",
        "permission_denied",
        "rate_limited",
        "provider_unavailable",
        "invalid_response",
    }:
        code = "provider_unavailable"
    return ConnectorHealth(
        status=(
            "REAUTH_REQUIRED"
            if code in {"authorization_revoked", "permission_denied"}
            else "ERROR"
        ),
        checked_at=now,
        error_code=code,
    )
