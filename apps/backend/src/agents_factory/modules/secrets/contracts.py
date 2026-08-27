from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError


class SecretAccessDenied(DomainError):
    """One sanitized surface for every secret lookup or binding failure."""

    def __init__(self) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/secret-access-denied",
            title="Secret Access Denied",
            status=403,
            detail="Secret access denied.",
            code="secret_access_denied",
        )


@dataclass(frozen=True, slots=True)
class SecretRef:
    """Opaque durable reference; it intentionally carries no tenant or value."""

    id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("SecretRef requires a UUID")


@dataclass(frozen=True, slots=True)
class SecretEnvelope:
    id: UUID
    tenant_id: UUID
    purpose: str
    record_context: str
    ciphertext: bytes
    wrapped_data_key: bytes
    payload_nonce: bytes
    key_nonce: bytes
    algorithm: str
    format_version: int
    key_id: str
    key_version: int


class KeyEncryptionProvider(Protocol):
    @property
    def key_id(self) -> str: ...

    @property
    def key_version(self) -> int: ...

    def wrap_data_key(self, data_key: bytes, *, nonce: bytes, aad: bytes) -> bytes: ...

    def unwrap_data_key(
        self,
        wrapped_data_key: bytes,
        *,
        nonce: bytes,
        aad: bytes,
    ) -> bytes: ...


class SecretRepository(Protocol):
    async def insert(
        self,
        *,
        context: TenantContext,
        envelope: SecretEnvelope,
    ) -> None: ...

    async def get(
        self,
        *,
        context: TenantContext,
        reference: SecretRef,
    ) -> SecretEnvelope | None: ...

    async def delete(
        self,
        *,
        context: TenantContext,
        reference: SecretRef,
    ) -> bool: ...


class SecretAuditRecorder(Protocol):
    async def record(
        self,
        *,
        context: TenantContext,
        event_type: str,
        entity_type: str,
        entity_id: UUID | None,
        payload: Mapping[str, object],
    ) -> UUID: ...
