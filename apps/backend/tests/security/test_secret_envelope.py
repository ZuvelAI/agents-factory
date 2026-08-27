from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import replace
from uuid import UUID

import pytest

from agents_factory.config import ConfigurationError
from agents_factory.modules.secrets.contracts import SecretAccessDenied
from agents_factory.modules.secrets.envelope import (
    EnvironmentMasterKeyProvider,
    SecretEnvelopeCipher,
    canonical_secret_aad,
)


SECRET_ID = UUID("019c0000-0000-7000-8000-000000000001")
TENANT_ID = UUID("019c0000-0000-7000-8000-000000000002")
OTHER_TENANT_ID = UUID("019c0000-0000-7000-8000-000000000003")
PURPOSE = "connector.authorization"
RECORD_CONTEXT = "connection:019c0000-0000-7000-8000-000000000004"
PLAINTEXT = b"task5a-super-secret-value"


def _encoded_key(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode()


def _provider(byte: int = 7) -> EnvironmentMasterKeyProvider:
    return EnvironmentMasterKeyProvider(
        environment={"APP_MASTER_KEY": _encoded_key(byte)}
    )


def _problem(error: SecretAccessDenied) -> tuple[object, ...]:
    return (
        error.type,
        error.title,
        error.status,
        error.detail,
        error.code,
    )


def test_canonical_aad_binds_every_approved_field_and_component() -> None:
    payload_aad = canonical_secret_aad(
        secret_id=SECRET_ID,
        tenant_id=TENANT_ID,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        version=1,
        component="payload",
    )
    key_aad = canonical_secret_aad(
        secret_id=SECRET_ID,
        tenant_id=TENANT_ID,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        version=1,
        component="data_key",
    )

    assert payload_aad == (
        b'{"component":"payload","id":"019c0000-0000-7000-8000-000000000001",'
        b'"purpose":"connector.authorization",'
        b'"record_context":"connection:019c0000-0000-7000-8000-000000000004",'
        b'"tenant_id":"019c0000-0000-7000-8000-000000000002",'
        b'"version":1}'
    )
    assert key_aad != payload_aad
    assert b'"component":"data_key"' in key_aad


def test_duplicate_plaintext_writes_use_fresh_deks_and_independent_nonces() -> None:
    cipher = SecretEnvelopeCipher(_provider())

    first = cipher.encrypt(
        secret_id=SECRET_ID,
        tenant_id=TENANT_ID,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        plaintext=PLAINTEXT,
    )
    second = cipher.encrypt(
        secret_id=SECRET_ID,
        tenant_id=TENANT_ID,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        plaintext=PLAINTEXT,
    )

    assert first.algorithm == "AES-256-GCM"
    assert first.format_version == 1
    assert (first.key_id, first.key_version) == ("environment-master-key", 1)
    assert len(first.payload_nonce) == len(first.key_nonce) == 12
    assert first.payload_nonce != first.key_nonce
    assert first.payload_nonce != second.payload_nonce
    assert first.key_nonce != second.key_nonce
    assert first.ciphertext != second.ciphertext
    assert first.wrapped_data_key != second.wrapped_data_key
    assert PLAINTEXT not in first.ciphertext
    assert PLAINTEXT not in first.wrapped_data_key
    assert (
        cipher.decrypt(
            first,
            tenant_id=TENANT_ID,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        )
        == PLAINTEXT
    )


def test_tampered_binding_metadata_ciphertext_and_key_fail_identically() -> None:
    cipher = SecretEnvelopeCipher(_provider())
    envelope = cipher.encrypt(
        secret_id=SECRET_ID,
        tenant_id=TENANT_ID,
        purpose=PURPOSE,
        record_context=RECORD_CONTEXT,
        plaintext=PLAINTEXT,
    )
    attempts: tuple[Callable[[], bytes], ...] = (
        lambda: cipher.decrypt(
            envelope,
            tenant_id=OTHER_TENANT_ID,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
        lambda: cipher.decrypt(
            envelope,
            tenant_id=TENANT_ID,
            purpose="connector.refresh",
            record_context=RECORD_CONTEXT,
        ),
        lambda: cipher.decrypt(
            envelope,
            tenant_id=TENANT_ID,
            purpose=PURPOSE,
            record_context="connection:other",
        ),
        lambda: cipher.decrypt(
            replace(envelope, id=OTHER_TENANT_ID),
            tenant_id=TENANT_ID,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
        lambda: cipher.decrypt(
            replace(envelope, format_version=2),
            tenant_id=TENANT_ID,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
        lambda: cipher.decrypt(
            replace(envelope, algorithm="AES-128-GCM"),
            tenant_id=TENANT_ID,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
        lambda: cipher.decrypt(
            replace(envelope, key_id="other-key"),
            tenant_id=TENANT_ID,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
        lambda: cipher.decrypt(
            replace(
                envelope,
                ciphertext=envelope.ciphertext[:-1]
                + bytes([envelope.ciphertext[-1] ^ 1]),
            ),
            tenant_id=TENANT_ID,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
        lambda: SecretEnvelopeCipher(_provider(8)).decrypt(
            envelope,
            tenant_id=TENANT_ID,
            purpose=PURPOSE,
            record_context=RECORD_CONTEXT,
        ),
    )

    problems: list[tuple[object, ...]] = []
    for attempt in attempts:
        with pytest.raises(SecretAccessDenied) as denied:
            attempt()
        problems.append(_problem(denied.value))

    assert all(problem == problems[0] for problem in problems)
    assert problems[0] == (
        "https://agents-factory.dev/problems/secret-access-denied",
        "Secret Access Denied",
        403,
        "Secret access denied.",
        "secret_access_denied",
    )
    assert PLAINTEXT.decode() not in repr(problems)


@pytest.mark.parametrize(
    "environment",
    (
        {},
        {"APP_MASTER_KEY": ""},
        {"APP_MASTER_KEY": "not/base64url"},
        {"APP_MASTER_KEY": _encoded_key(1) + "=" + "="},
        {"APP_MASTER_KEY": base64.urlsafe_b64encode(b"x" * 31).rstrip(b"=").decode()},
        {"APP_MASTER_KEY": base64.urlsafe_b64encode(b"x" * 33).rstrip(b"=").decode()},
    ),
)
def test_environment_provider_rejects_missing_or_non_256_bit_keys_without_echo(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError) as invalid:
        EnvironmentMasterKeyProvider(environment=environment)

    assert invalid.value.invalid_variables == ("APP_MASTER_KEY",)
    assert "APP_MASTER_KEY" in str(invalid.value)
    rejected_value = environment.get("APP_MASTER_KEY")
    if rejected_value:
        assert rejected_value not in str(invalid.value)


def test_environment_provider_accepts_canonical_padded_or_unpadded_base64url() -> None:
    encoded = _encoded_key(9)
    unpadded = EnvironmentMasterKeyProvider(environment={"APP_MASTER_KEY": encoded})
    padded = EnvironmentMasterKeyProvider(environment={"APP_MASTER_KEY": f"{encoded}="})

    assert (unpadded.key_id, unpadded.key_version) == (
        "environment-master-key",
        1,
    )
    assert (padded.key_id, padded.key_version) == (
        "environment-master-key",
        1,
    )
    assert encoded not in repr(unpadded)
    assert repr(unpadded) == "EnvironmentMasterKeyProvider([REDACTED])"
