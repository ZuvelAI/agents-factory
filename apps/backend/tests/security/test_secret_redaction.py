from __future__ import annotations

import base64
import json
import pickle
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, fields
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict

from agents_factory.common.context import TenantContext
from agents_factory.modules.secrets.contracts import (
    SecretAccessDenied,
    SecretEnvelope,
    SecretRef,
)
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.secrets.repository import SecretVault


TENANT_A = UUID("019c1000-0000-7000-8000-000000000001")
TENANT_B = UUID("019c1000-0000-7000-8000-000000000002")
ACTOR = UUID("019c1000-0000-7000-8000-000000000003")
CORRELATION = UUID("019c1000-0000-7000-8000-000000000004")
PURPOSE = "connector.authorization"
RECORD_CONTEXT = "connection:019c1000-0000-7000-8000-000000000005"
PLAINTEXT = b"redaction-test-secret-value"


def _context(tenant_id: UUID, *, actor_id: UUID | None = ACTOR) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type="platform_admin",
        correlation_id=CORRELATION,
    )


def _provider(byte: int = 3) -> EnvironmentMasterKeyProvider:
    encoded = base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode()
    return EnvironmentMasterKeyProvider(environment={"APP_MASTER_KEY": encoded})


class MemorySecretRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, SecretEnvelope] = {}

    async def insert(
        self,
        *,
        context: TenantContext,
        envelope: SecretEnvelope,
    ) -> None:
        if envelope.tenant_id != context.tenant_id:
            raise AssertionError("vault crossed its tenant boundary")
        self.records[envelope.id] = envelope

    async def get(
        self,
        *,
        context: TenantContext,
        reference: SecretRef,
    ) -> SecretEnvelope | None:
        envelope = self.records.get(reference.id)
        if envelope is None or envelope.tenant_id != context.tenant_id:
            return None
        return envelope

    async def delete(
        self,
        *,
        context: TenantContext,
        reference: SecretRef,
    ) -> bool:
        envelope = await self.get(context=context, reference=reference)
        if envelope is None:
            return False
        del self.records[reference.id]
        return True


@dataclass(frozen=True, slots=True)
class AuditEntry:
    tenant_id: UUID
    event_type: str
    entity_id: UUID | None
    payload: dict[str, object]


class CollectingAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(
        self,
        *,
        context: TenantContext,
        event_type: str,
        entity_type: str,
        entity_id: UUID | None,
        payload: Mapping[str, object],
    ) -> UUID:
        assert entity_type == "secret_envelope"
        self.entries.append(
            AuditEntry(
                tenant_id=context.tenant_id,
                event_type=event_type,
                entity_id=entity_id,
                payload=dict(payload),
            )
        )
        return CORRELATION


class UnsafePayload(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: ResolvedSecret


def _problem(error: SecretAccessDenied) -> tuple[object, ...]:
    return (
        error.type,
        error.title,
        error.status,
        error.detail,
        error.code,
    )


def test_secret_ref_is_uuid_only_and_resolved_value_is_redacted_nonserializable() -> (
    None
):
    reference = SecretRef(id=UUID("019c1000-0000-7000-8000-000000000010"))
    resolved = ResolvedSecret(PLAINTEXT)

    assert [field.name for field in fields(reference)] == ["id"]
    assert asdict(reference) == {"id": reference.id}
    with pytest.raises(TypeError):
        vars(reference)
    assert str(resolved) == repr(resolved) == "[REDACTED]"
    assert resolved.reveal() == PLAINTEXT
    assert PLAINTEXT.decode() not in repr(resolved)
    with pytest.raises(TypeError):
        json.dumps({"secret": resolved})
    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(resolved)
    with pytest.raises(Exception) as pydantic_error:
        UnsafePayload(value=resolved).model_dump_json()
    assert PLAINTEXT.decode() not in str(pydantic_error.value)


@pytest.mark.asyncio
async def test_vault_returns_only_opaque_refs_and_audits_redacted_metadata() -> None:
    repository = MemorySecretRepository()
    audit = CollectingAudit()
    vault = SecretVault(repository=repository, audit=audit, key_provider=_provider())
    context = _context(TENANT_A)

    first_ref = await vault.store(
        context=context,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        plaintext=PLAINTEXT,
    )
    second_ref = await vault.store(
        context=context,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        plaintext=PLAINTEXT,
    )
    resolved = await vault.load(
        context=context,
        reference=first_ref,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
    )

    first = repository.records[first_ref.id]
    second = repository.records[second_ref.id]
    assert first_ref != second_ref
    assert first.ciphertext != second.ciphertext
    assert first.payload_nonce != second.payload_nonce
    assert first.key_nonce != second.key_nonce
    assert resolved.reveal() == PLAINTEXT
    assert all("plaintext" not in field.name for field in fields(first))
    emitted = repr(audit.entries)
    assert PLAINTEXT.decode() not in emitted
    assert _provider().__repr__() == "EnvironmentMasterKeyProvider([REDACTED])"
    assert [entry.event_type for entry in audit.entries] == [
        "secret.stored",
        "secret.stored",
        "secret.loaded",
    ]
    assert all(
        set(entry.payload)
        <= {
            "operation",
            "outcome",
            "purpose",
            "record_context",
            "algorithm",
            "format_version",
            "key_id",
            "key_version",
        }
        for entry in audit.entries
    )


@pytest.mark.asyncio
async def test_all_resolution_denials_share_one_surface_and_never_echo_inputs() -> None:
    repository = MemorySecretRepository()
    audit = CollectingAudit()
    vault = SecretVault(repository=repository, audit=audit, key_provider=_provider())
    reference = await vault.store(
        context=_context(TENANT_A),
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        plaintext=PLAINTEXT,
    )
    wrong_key_vault = SecretVault(
        repository=repository,
        audit=audit,
        key_provider=_provider(4),
    )
    attempts: tuple[Callable[[], Awaitable[ResolvedSecret]], ...] = (
        lambda: vault.load(
            context=_context(TENANT_B),
            reference=reference,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
        lambda: vault.load(
            context=_context(TENANT_A),
            reference=reference,
            purpose="wrong-purpose",
            record_context=RECORD_CONTEXT,
        ),
        lambda: vault.load(
            context=_context(TENANT_A),
            reference=reference,
            purpose=PURPOSE,
            record_context="wrong-context",
        ),
        lambda: vault.load(
            context=_context(TENANT_A, actor_id=None),
            reference=reference,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
        lambda: vault.load(
            context=None,
            reference=reference,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
        lambda: wrong_key_vault.load(
            context=_context(TENANT_A),
            reference=reference,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
    )

    problems: list[tuple[object, ...]] = []
    for attempt in attempts:
        with pytest.raises(SecretAccessDenied) as denied:
            await attempt()
        problems.append(_problem(denied.value))

    assert all(problem == problems[0] for problem in problems)
    unsafe_output = repr(problems) + repr(audit.entries)
    for forbidden in (
        PLAINTEXT.decode(),
        "wrong-purpose",
        "wrong-context",
    ):
        assert forbidden not in unsafe_output
    assert [entry.event_type for entry in audit.entries].count(
        "secret.access_denied"
    ) == 5
    denied_entries = [
        entry for entry in audit.entries if entry.event_type == "secret.access_denied"
    ]
    assert all(
        entry.payload == {"operation": "load", "outcome": "denied"}
        for entry in denied_entries
    )


@pytest.mark.asyncio
async def test_delete_requires_the_same_binding_and_audits_without_values() -> None:
    repository = MemorySecretRepository()
    audit = CollectingAudit()
    vault = SecretVault(repository=repository, audit=audit, key_provider=_provider())
    context = _context(TENANT_A)
    reference = await vault.store(
        context=context,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        plaintext=PLAINTEXT,
    )

    with pytest.raises(SecretAccessDenied):
        await vault.delete(
            context=context,
            reference=reference,
            purpose=PURPOSE,
            record_context="wrong-context",
        )
    await vault.delete(
        context=context,
        reference=reference,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
    )

    assert reference.id not in repository.records
    assert [entry.event_type for entry in audit.entries] == [
        "secret.stored",
        "secret.access_denied",
        "secret.deleted",
    ]
    assert PLAINTEXT.decode() not in repr(audit.entries)
