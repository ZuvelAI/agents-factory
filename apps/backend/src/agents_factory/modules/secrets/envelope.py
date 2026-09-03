from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agents_factory.config import ConfigurationError
from agents_factory.modules.secrets.contracts import (
    KeyEncryptionProvider,
    SecretAccessDenied,
    SecretEnvelope,
)


ALGORITHM = "AES-256-GCM"
FORMAT_VERSION = 1
DATA_KEY_BYTES = 32
NONCE_BYTES = 12
_BASE64URL_256 = re.compile(r"[A-Za-z0-9_-]{43}=?")
EnvelopeComponent = Literal["payload", "data_key"]


def canonical_secret_aad(
    *,
    secret_id: UUID,
    tenant_id: UUID,
    purpose: str,
    record_context: str,
    version: int,
    component: EnvelopeComponent,
) -> bytes:
    """Build the stable authenticated binding shared by every key provider."""

    return json.dumps(
        {
            "id": str(secret_id),
            "tenant_id": str(tenant_id),
            "purpose": purpose,
            "record_context": record_context,
            "version": version,
            "component": component,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class EnvironmentMasterKeyProvider:
    """AES-GCM key wrapper backed only by the server process environment."""

    __slots__ = ("_key_version", "_master_key")

    def __init__(self, *, environment: Mapping[str, str] | None = None) -> None:
        source = os.environ if environment is None else environment
        encoded_key = source.get("APP_MASTER_KEY")
        try:
            if encoded_key is None or not _BASE64URL_256.fullmatch(encoded_key):
                raise ValueError
            unpadded = encoded_key.removesuffix("=")
            decoded = base64.b64decode(
                f"{unpadded}=",
                altchars=b"-_",
                validate=True,
            )
            canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode()
            if len(decoded) != DATA_KEY_BYTES or canonical != unpadded:
                raise ValueError
        except (binascii.Error, UnicodeEncodeError, ValueError):
            raise ConfigurationError(invalid_variables=("APP_MASTER_KEY",)) from None
        self._master_key = decoded
        try:
            self._key_version = int(source.get("APP_MASTER_KEY_VERSION", "1"))
            if self._key_version < 1:
                raise ValueError
        except ValueError:
            raise ConfigurationError(
                invalid_variables=("APP_MASTER_KEY_VERSION",)
            ) from None

    @property
    def key_id(self) -> str:
        return "environment-master-key"

    @property
    def key_version(self) -> int:
        return self._key_version

    def wrap_data_key(self, data_key: bytes, *, nonce: bytes, aad: bytes) -> bytes:
        if len(data_key) != DATA_KEY_BYTES or len(nonce) != NONCE_BYTES:
            raise SecretAccessDenied()
        try:
            return AESGCM(self._master_key).encrypt(nonce, data_key, aad)
        except (OverflowError, TypeError, ValueError):
            raise SecretAccessDenied() from None

    def unwrap_data_key(
        self,
        wrapped_data_key: bytes,
        *,
        nonce: bytes,
        aad: bytes,
    ) -> bytes:
        if len(nonce) != NONCE_BYTES:
            raise SecretAccessDenied()
        try:
            data_key = AESGCM(self._master_key).decrypt(
                nonce,
                wrapped_data_key,
                aad,
            )
        except (InvalidTag, OverflowError, TypeError, ValueError):
            raise SecretAccessDenied() from None
        if len(data_key) != DATA_KEY_BYTES:
            raise SecretAccessDenied()
        return data_key

    def __repr__(self) -> str:
        return "EnvironmentMasterKeyProvider([REDACTED])"


class SecretEnvelopeCipher:
    def __init__(self, key_provider: KeyEncryptionProvider) -> None:
        self._key_provider = key_provider

    def encrypt(
        self,
        *,
        secret_id: UUID,
        tenant_id: UUID,
        purpose: str,
        record_context: str,
        plaintext: bytes,
    ) -> SecretEnvelope:
        if not _valid_binding(purpose, record_context) or not plaintext:
            raise SecretAccessDenied()

        data_key = AESGCM.generate_key(bit_length=256)
        payload_nonce = secrets.token_bytes(NONCE_BYTES)
        key_nonce = secrets.token_bytes(NONCE_BYTES)
        payload_aad = canonical_secret_aad(
            secret_id=secret_id,
            tenant_id=tenant_id,
            purpose=purpose,
            record_context=record_context,
            version=FORMAT_VERSION,
            component="payload",
        )
        key_aad = canonical_secret_aad(
            secret_id=secret_id,
            tenant_id=tenant_id,
            purpose=purpose,
            record_context=record_context,
            version=FORMAT_VERSION,
            component="data_key",
        )
        try:
            ciphertext = AESGCM(data_key).encrypt(
                payload_nonce,
                plaintext,
                payload_aad,
            )
            wrapped_data_key = self._key_provider.wrap_data_key(
                data_key,
                nonce=key_nonce,
                aad=key_aad,
            )
        except SecretAccessDenied:
            raise
        except (OverflowError, TypeError, ValueError):
            raise SecretAccessDenied() from None
        return SecretEnvelope(
            id=secret_id,
            tenant_id=tenant_id,
            purpose=purpose,
            record_context=record_context,
            ciphertext=ciphertext,
            wrapped_data_key=wrapped_data_key,
            payload_nonce=payload_nonce,
            key_nonce=key_nonce,
            algorithm=ALGORITHM,
            format_version=FORMAT_VERSION,
            key_id=self._key_provider.key_id,
            key_version=self._key_provider.key_version,
        )

    def decrypt(
        self,
        envelope: SecretEnvelope,
        *,
        tenant_id: UUID,
        purpose: str,
        record_context: str,
    ) -> bytes:
        if (
            envelope.tenant_id != tenant_id
            or envelope.purpose != purpose
            or envelope.record_context != record_context
            or envelope.algorithm != ALGORITHM
            or envelope.format_version != FORMAT_VERSION
            or envelope.key_id != self._key_provider.key_id
            or envelope.key_version != self._key_provider.key_version
            or len(envelope.payload_nonce) != NONCE_BYTES
            or len(envelope.key_nonce) != NONCE_BYTES
            or len(envelope.ciphertext) < 16
            or len(envelope.wrapped_data_key) != DATA_KEY_BYTES + 16
        ):
            raise SecretAccessDenied()

        payload_aad = canonical_secret_aad(
            secret_id=envelope.id,
            tenant_id=tenant_id,
            purpose=purpose,
            record_context=record_context,
            version=envelope.format_version,
            component="payload",
        )
        key_aad = canonical_secret_aad(
            secret_id=envelope.id,
            tenant_id=tenant_id,
            purpose=purpose,
            record_context=record_context,
            version=envelope.format_version,
            component="data_key",
        )
        try:
            data_key = self._key_provider.unwrap_data_key(
                envelope.wrapped_data_key,
                nonce=envelope.key_nonce,
                aad=key_aad,
            )
            return AESGCM(data_key).decrypt(
                envelope.payload_nonce,
                envelope.ciphertext,
                payload_aad,
            )
        except SecretAccessDenied:
            raise
        except (InvalidTag, OverflowError, TypeError, ValueError):
            raise SecretAccessDenied() from None


def _valid_binding(purpose: str, record_context: str) -> bool:
    return (
        isinstance(purpose, str)
        and purpose == purpose.strip()
        and 0 < len(purpose) <= 200
        and isinstance(record_context, str)
        and record_context == record_context.strip()
        and 0 < len(record_context) <= 500
    )
