from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from agents_factory.modules.integrations.models import (
    IntegrationError,
    SafeModel,
    V1_CONNECTION_NAMES,
)
from agents_factory.modules.secrets.redaction import ResolvedSecret


PKCE_PURPOSE = "integrations.oauth_pkce"
ProviderFailureCode = Literal[
    "authorization_revoked",
    "permission_denied",
    "rate_limited",
    "provider_unavailable",
    "invalid_response",
]


class ProviderFailure(Exception):
    def __init__(self, code: ProviderFailureCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OAuthConfiguration:
    authorization_endpoint: str
    client_id: str
    redirect_uri: str
    allowed_scopes: frozenset[str]

    def __post_init__(self) -> None:
        for value in (self.authorization_endpoint, self.redirect_uri):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("OAuth endpoints must be fixed HTTPS URLs")
        if not self.client_id or not self.allowed_scopes:
            raise ValueError("OAuth requires a client and an explicit scope allowlist")

    def authorize_url(
        self, *, state: str, code_challenge: str, scopes: tuple[str, ...]
    ) -> str:
        if not scopes or not set(scopes).issubset(self.allowed_scopes):
            raise IntegrationError("integration_scopes_invalid", status=400)
        return (
            self.authorization_endpoint
            + "?"
            + urlencode(
                {
                    "client_id": self.client_id,
                    "redirect_uri": self.redirect_uri,
                    "response_type": "code",
                    "scope": " ".join(scopes),
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                    "access_type": "offline",
                    "prompt": "consent",
                }
            )
        )


@dataclass(frozen=True, slots=True)
class AuthorizationGrant:
    # Opaque provider payload: only its adapter understands token/refresh fields.
    credential: ResolvedSecret = field(repr=False)
    granted_scopes: tuple[str, ...] = ()
    expires_at: datetime | None = None


class CredentialProvider(Protocol):
    @property
    def oauth(self) -> OAuthConfiguration | None: ...

    async def exchange(
        self, *, code: ResolvedSecret, verifier: ResolvedSecret
    ) -> AuthorizationGrant: ...

    async def refresh(self, credential: ResolvedSecret) -> AuthorizationGrant: ...

    async def revoke(self, credential: ResolvedSecret) -> None: ...

    async def check_health(self, credential: ResolvedSecret) -> None: ...


class ProviderRegistry:
    """Only code-owned, approved v1 adapters; not a user-configurable REST gateway."""

    def __init__(self) -> None:
        self._providers: dict[str, CredentialProvider] = {}

    def register(self, name: str, provider: CredentialProvider) -> None:
        if name not in V1_CONNECTION_NAMES or name in self._providers:
            raise ValueError("unsupported or duplicate credential provider")
        self._providers[name] = provider

    def get(self, name: str) -> CredentialProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise IntegrationError("integration_not_configured", status=503) from None

    def contains(self, name: str) -> bool:
        return name in self._providers


class OAuthStart(SafeModel):
    connection_id: UUID
    authorization_url: str
    expires_at: datetime
    requested_scopes: tuple[str, ...]


def state_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def pkce_challenge(value: bytes) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode()
    )


def new_oauth_proof() -> tuple[str, ResolvedSecret, str]:
    state = secrets.token_urlsafe(32)
    verifier = ResolvedSecret(secrets.token_urlsafe(48).encode())
    return state, verifier, pkce_challenge(verifier.reveal())
