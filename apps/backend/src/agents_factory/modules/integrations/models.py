from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agents_factory.common.errors import DomainError
from agents_factory.modules.secrets.contracts import SecretRef


ConnectionStatus = Literal[
    "PENDING", "CONNECTED", "REAUTH_REQUIRED", "REVOKING", "REVOKED"
]
HealthStatus = Literal["UNKNOWN", "HEALTHY", "REAUTH_REQUIRED", "ERROR"]
AuthKind = Literal["OAUTH2", "API_KEY", "META_EMBEDDED"]
CatalogAvailability = Literal["AVAILABLE", "SETUP_REQUIRED", "COMING_LATER"]
V1_CONNECTION_NAMES = frozenset(
    {"google_calendar", "gmail", "google_drive", "google_sheets", "woocommerce"}
)


class IntegrationError(DomainError):
    def __init__(self, code: str, *, status: int = 409) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/integration-error",
            title="Integration Error",
            status=status,
            detail="The integration operation could not be completed.",
            code=code,
        )


class SafeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ConnectorHealth(SafeModel):
    status: HealthStatus = "UNKNOWN"
    checked_at: datetime | None = None
    error_code: str | None = None


class ConnectionSummary(SafeModel):
    id: UUID
    tenant_id: UUID
    connector_name: str
    auth_kind: AuthKind
    status: ConnectionStatus
    requested_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...]
    expires_at: datetime | None
    health: ConnectorHealth


class CatalogEntry(SafeModel):
    connector_name: str
    display_name: str
    available: bool
    availability: CatalogAvailability
    auth_kind: AuthKind | None
    required_scopes: tuple[str, ...]
    supported_operations: tuple[str, ...]
    connections: tuple[ConnectionSummary, ...]
    note: str


@dataclass(frozen=True, slots=True)
class IntegrationConnection:
    id: UUID
    tenant_id: UUID
    connector_name: str
    auth_kind: AuthKind
    status: ConnectionStatus = "PENDING"
    credential_ref: SecretRef | None = field(default=None, repr=False)
    requested_scopes: tuple[str, ...] = ()
    granted_scopes: tuple[str, ...] = ()
    authorization_version: int = 0
    expires_at: datetime | None = None
    health: ConnectorHealth = field(default_factory=ConnectorHealth)

    @property
    def credential_purpose(self) -> str:
        return f"integrations.{self.connector_name}.credentials"

    @property
    def credential_context(self) -> str:
        return f"integration_connection:{self.id}"

    def summary(self) -> ConnectionSummary:
        return ConnectionSummary(
            id=self.id,
            tenant_id=self.tenant_id,
            connector_name=self.connector_name,
            auth_kind=self.auth_kind,
            status=self.status,
            requested_scopes=self.requested_scopes,
            granted_scopes=self.granted_scopes,
            expires_at=self.expires_at,
            health=self.health,
        )


@dataclass(frozen=True, slots=True)
class OAuthState:
    state_digest: str
    tenant_id: UUID
    connection_id: UUID
    admin_user_id: UUID
    admin_session_id: UUID
    authorization_version: int
    verifier_ref: SecretRef = field(repr=False)
    code_challenge: str
    expires_at: datetime

    @property
    def verifier_context(self) -> str:
        return f"integration_oauth_state:{self.state_digest}"
