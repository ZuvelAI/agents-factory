from __future__ import annotations

import hashlib
import hmac

import pytest
from pydantic import SecretStr

from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider


APP_SECRET = "meta-app-secret-test-value"


def _signature(raw_body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_valid_signature_is_bound_to_the_exact_raw_request_bytes() -> None:
    provider = MetaCloudApiProvider(app_secret=SecretStr(APP_SECRET))
    raw_body = b'{"object":"whatsapp_business_account","entry":[]}'

    assert provider.verify_signature(
        raw_body=raw_body,
        signature=_signature(raw_body),
    )
    assert not provider.verify_signature(
        raw_body=raw_body + b"\n",
        signature=_signature(raw_body),
    )


@pytest.mark.parametrize(
    "signature",
    (
        "",
        "sha1=8d969eef6ecad3c29a3a629280e686cff8ca",
        "SHA256=8d969eef6ecad3c29a3a629280e686cff8ca",
        "sha256=not-hex",
        "sha256=" + "0" * 63,
        "sha256=" + "0" * 65,
    ),
)
def test_malformed_or_non_sha256_signatures_fail_closed(signature: str) -> None:
    provider = MetaCloudApiProvider(app_secret=SecretStr(APP_SECRET))

    assert not provider.verify_signature(raw_body=b"{}", signature=signature)


def test_wrong_signature_fails_without_disclosing_the_app_secret() -> None:
    provider = MetaCloudApiProvider(app_secret=SecretStr(APP_SECRET))

    assert not provider.verify_signature(
        raw_body=b"{}",
        signature="sha256=" + "0" * 64,
    )
    assert APP_SECRET not in repr(provider)
