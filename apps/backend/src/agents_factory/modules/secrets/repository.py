from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.database import set_tenant_context
from agents_factory.modules.secrets.contracts import (
    KeyEncryptionProvider,
    SecretAccessDenied,
    SecretAuditRecorder,
    SecretEnvelope,
    SecretRef,
    SecretRepository,
)
from agents_factory.modules.secrets.envelope import SecretEnvelopeCipher
from agents_factory.modules.secrets.redaction import ResolvedSecret


class SecretEnvelopeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        context: TenantContext,
        envelope: SecretEnvelope,
    ) -> None:
        await set_tenant_context(self._session, context.tenant_id)
        await self._session.execute(
            text(
                "INSERT INTO public.secret_envelopes "
                "(id, tenant_id, purpose, record_context, ciphertext, "
                "wrapped_data_key, payload_nonce, key_nonce, algorithm, "
                "format_version, key_id, key_version) VALUES "
                "(:id, :tenant_id, :purpose, :record_context, :ciphertext, "
                ":wrapped_data_key, :payload_nonce, :key_nonce, :algorithm, "
                ":format_version, :key_id, :key_version)"
            ),
            _envelope_parameters(envelope),
        )

    async def get(
        self,
        *,
        context: TenantContext,
        reference: SecretRef,
    ) -> SecretEnvelope | None:
        await set_tenant_context(self._session, context.tenant_id)
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, purpose, record_context, ciphertext, "
                "wrapped_data_key, payload_nonce, key_nonce, algorithm, "
                "format_version, key_id, key_version "
                "FROM public.secret_envelopes WHERE id = :id"
            ),
            {"id": reference.id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else _envelope_from_mapping(row)

    async def delete(
        self,
        *,
        context: TenantContext,
        reference: SecretRef,
    ) -> bool:
        await set_tenant_context(self._session, context.tenant_id)
        result = await self._session.execute(
            text("DELETE FROM public.secret_envelopes WHERE id = :id RETURNING id"),
            {"id": reference.id},
        )
        return result.scalar_one_or_none() is not None


class _CommittedAuditRecorder:
    """Persist denial evidence outside the caller transaction that will roll back."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def record(
        self,
        *,
        context: TenantContext,
        event_type: str,
        entity_type: str,
        entity_id: UUID | None,
        payload: Mapping[str, object],
    ) -> UUID:
        async with self._session_factory.begin() as session:
            return await AuditService(session).record(
                context=context,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
            )


class SecretVault:
    def __init__(
        self,
        *,
        repository: SecretRepository,
        audit: SecretAuditRecorder,
        key_provider: KeyEncryptionProvider,
        denial_audit: SecretAuditRecorder | None = None,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._denial_audit = audit if denial_audit is None else denial_audit
        self._cipher = SecretEnvelopeCipher(key_provider)

    @classmethod
    def for_session(
        cls,
        session: AsyncSession,
        *,
        key_provider: KeyEncryptionProvider,
    ) -> SecretVault:
        bind = session.bind
        if not isinstance(bind, AsyncEngine):
            raise RuntimeError("secret vault requires an engine-bound session")
        return cls(
            repository=SecretEnvelopeRepository(session),
            audit=AuditService(session),
            denial_audit=_CommittedAuditRecorder(bind),
            key_provider=key_provider,
        )

    async def store(
        self,
        *,
        context: TenantContext | None,
        purpose: str,
        record_context: str,
        plaintext: bytes,
    ) -> SecretRef:
        authenticated = await self._require_context(context, operation="store")
        if (
            not _valid_binding(purpose, record_context)
            or not isinstance(plaintext, bytes)
            or not plaintext
        ):
            await self._deny(authenticated, operation="store", reference=None)
        secret_id = new_uuid7()
        try:
            envelope = self._cipher.encrypt(
                secret_id=secret_id,
                tenant_id=authenticated.tenant_id,
                purpose=purpose,
                record_context=record_context,
                plaintext=plaintext,
            )
            await self._repository.insert(context=authenticated, envelope=envelope)
            await self._audit.record(
                context=authenticated,
                event_type="secret.stored",
                entity_type="secret_envelope",
                entity_id=secret_id,
                payload=_success_metadata(envelope, operation="store"),
            )
        except SecretAccessDenied:
            raise
        except Exception:
            await self._deny(
                authenticated,
                operation="store",
                reference=SecretRef(secret_id),
            )
        return SecretRef(secret_id)

    async def load(
        self,
        *,
        context: TenantContext | None,
        reference: SecretRef,
        purpose: str,
        record_context: str,
    ) -> ResolvedSecret:
        authenticated = await self._require_context(
            context,
            operation="load",
            reference=reference,
        )
        if not _valid_binding(purpose, record_context):
            await self._deny(authenticated, operation="load", reference=reference)
        try:
            envelope = await self._repository.get(
                context=authenticated,
                reference=reference,
            )
        except Exception:
            await self._deny(authenticated, operation="load", reference=reference)
        if envelope is None:
            await self._deny(authenticated, operation="load", reference=reference)
        try:
            plaintext = self._cipher.decrypt(
                envelope,
                tenant_id=authenticated.tenant_id,
                purpose=purpose,
                record_context=record_context,
            )
            await self._audit.record(
                context=authenticated,
                event_type="secret.loaded",
                entity_type="secret_envelope",
                entity_id=reference.id,
                payload=_success_metadata(envelope, operation="load"),
            )
        except SecretAccessDenied:
            await self._deny(authenticated, operation="load", reference=reference)
        except Exception:
            await self._deny(authenticated, operation="load", reference=reference)
        return ResolvedSecret(plaintext)

    async def delete(
        self,
        *,
        context: TenantContext | None,
        reference: SecretRef,
        purpose: str,
        record_context: str,
    ) -> None:
        authenticated = await self._require_context(
            context,
            operation="delete",
            reference=reference,
        )
        if not _valid_binding(purpose, record_context):
            await self._deny(authenticated, operation="delete", reference=reference)
        try:
            envelope = await self._repository.get(
                context=authenticated,
                reference=reference,
            )
        except Exception:
            await self._deny(authenticated, operation="delete", reference=reference)
        if envelope is None:
            await self._deny(authenticated, operation="delete", reference=reference)
        try:
            self._cipher.decrypt(
                envelope,
                tenant_id=authenticated.tenant_id,
                purpose=purpose,
                record_context=record_context,
            )
        except SecretAccessDenied:
            await self._deny(authenticated, operation="delete", reference=reference)
        try:
            deleted = await self._repository.delete(
                context=authenticated,
                reference=reference,
            )
            if not deleted:
                await self._deny(
                    authenticated,
                    operation="delete",
                    reference=reference,
                )
            await self._audit.record(
                context=authenticated,
                event_type="secret.deleted",
                entity_type="secret_envelope",
                entity_id=reference.id,
                payload=_success_metadata(envelope, operation="delete"),
            )
        except SecretAccessDenied:
            raise
        except Exception:
            await self._deny(authenticated, operation="delete", reference=reference)

    async def _require_context(
        self,
        context: TenantContext | None,
        *,
        operation: str,
        reference: SecretRef | None = None,
    ) -> TenantContext:
        if not isinstance(context, TenantContext):
            raise SecretAccessDenied()
        if context.actor_id is None:
            await self._deny(context, operation=operation, reference=reference)
        return context

    async def _deny(
        self,
        context: TenantContext,
        *,
        operation: str,
        reference: SecretRef | None,
    ) -> NoReturn:
        try:
            await self._denial_audit.record(
                context=context,
                event_type="secret.access_denied",
                entity_type="secret_envelope",
                entity_id=None if reference is None else reference.id,
                payload={"operation": operation, "outcome": "denied"},
            )
        except Exception:
            pass
        raise SecretAccessDenied()


def _valid_binding(purpose: str, record_context: str) -> bool:
    return (
        isinstance(purpose, str)
        and purpose == purpose.strip()
        and 0 < len(purpose) <= 200
        and isinstance(record_context, str)
        and record_context == record_context.strip()
        and 0 < len(record_context) <= 500
    )


def _success_metadata(
    envelope: SecretEnvelope,
    *,
    operation: str,
) -> dict[str, object]:
    return {
        "operation": operation,
        "outcome": "succeeded",
        "purpose": envelope.purpose,
        "record_context": envelope.record_context,
        "algorithm": envelope.algorithm,
        "format_version": envelope.format_version,
        "key_id": envelope.key_id,
        "key_version": envelope.key_version,
    }


def _envelope_parameters(envelope: SecretEnvelope) -> dict[str, object]:
    return {
        "id": envelope.id,
        "tenant_id": envelope.tenant_id,
        "purpose": envelope.purpose,
        "record_context": envelope.record_context,
        "ciphertext": envelope.ciphertext,
        "wrapped_data_key": envelope.wrapped_data_key,
        "payload_nonce": envelope.payload_nonce,
        "key_nonce": envelope.key_nonce,
        "algorithm": envelope.algorithm,
        "format_version": envelope.format_version,
        "key_id": envelope.key_id,
        "key_version": envelope.key_version,
    }


def _envelope_from_mapping(row: RowMapping) -> SecretEnvelope:
    return SecretEnvelope(
        id=row["id"],
        tenant_id=row["tenant_id"],
        purpose=row["purpose"],
        record_context=row["record_context"],
        ciphertext=bytes(row["ciphertext"]),
        wrapped_data_key=bytes(row["wrapped_data_key"]),
        payload_nonce=bytes(row["payload_nonce"]),
        key_nonce=bytes(row["key_nonce"]),
        algorithm=row["algorithm"],
        format_version=row["format_version"],
        key_id=row["key_id"],
        key_version=row["key_version"],
    )
