from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt import PyJWK
from jwt.exceptions import PyJWKClientError

from agents_factory.common.errors import DomainError
from agents_factory.common.security import (
    AdminPrincipal,
    JwksTokenVerifier,
    PlatformAdminAuthorizer,
)


ISSUER = "https://project.supabase.co/auth/v1"
AUDIENCE = "authenticated"
SESSION_ID = uuid4()
USER_ID = uuid4()


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class StaticJwksClient:
    def __init__(self, keys: dict[str, PyJWK]) -> None:
        self._keys = keys

    def get_signing_key_from_jwt(self, access_jwt: str) -> PyJWK:
        kid = jwt.get_unverified_header(access_jwt).get("kid")
        if not isinstance(kid, str) or kid not in self._keys:
            raise PyJWKClientError("unknown signing key")
        return self._keys[kid]


class MembershipResult:
    def __init__(self, member: bool) -> None:
        self._member = member

    def scalar_one(self) -> bool:
        return self._member


class MembershipSession:
    def __init__(self, *, member: bool) -> None:
        self.member = member
        self.statements: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(
        self,
        statement: object,
        parameters: dict[str, Any] | None = None,
    ) -> MembershipResult:
        rendered = str(statement)
        self.statements.append((rendered, parameters))
        if "platform_admins" in rendered:
            return MembershipResult(self.member)
        return MembershipResult(False)


@pytest.fixture
def rsa_signing_material() -> tuple[object, dict[str, PyJWK]]:
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = signing_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "rsa-test-key",
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }
    return signing_key, {"rsa-test-key": PyJWK.from_dict(jwk)}


@pytest.fixture
def ec_signing_material() -> tuple[object, dict[str, PyJWK]]:
    signing_key = ec.generate_private_key(ec.SECP256R1())
    numbers = signing_key.public_key().public_numbers()
    width = 32

    def encode(value: int) -> str:
        return (
            base64.urlsafe_b64encode(value.to_bytes(width, "big")).rstrip(b"=").decode()
        )

    jwk = {
        "kty": "EC",
        "kid": "ec-test-key",
        "use": "sig",
        "alg": "ES256",
        "crv": "P-256",
        "x": encode(numbers.x),
        "y": encode(numbers.y),
    }
    return signing_key, {"ec-test-key": PyJWK.from_dict(jwk)}


def _claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "sub": str(USER_ID),
        "session_id": str(SESSION_ID),
        "role": "authenticated",
        "is_anonymous": False,
        "app_metadata": {"platform_role": "platform_admin"},
        "user_metadata": {},
    }
    claims.update(overrides)
    return claims


def _encode(
    key: object,
    claims: dict[str, object],
    *,
    algorithm: str = "RS256",
    kid: str = "rsa-test-key",
) -> str:
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


def _verifier(keys: dict[str, PyJWK]) -> JwksTokenVerifier:
    return JwksTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_client=StaticJwksClient(keys),
    )


async def _expect_error(
    awaitable: object,
    *,
    status: int,
    code: str,
) -> DomainError:
    with pytest.raises(DomainError) as caught:
        await awaitable  # type: ignore[misc]
    assert caught.value.status == status
    assert caught.value.code == code
    return caught.value


@pytest.mark.asyncio
async def test_missing_bearer_token_returns_stable_401_contract(
    rsa_signing_material: tuple[object, dict[str, PyJWK]],
) -> None:
    _, keys = rsa_signing_material
    authorizer = PlatformAdminAuthorizer(_verifier(keys))

    error = await _expect_error(
        authorizer.authorize(
            authorization=None, session=MembershipSession(member=True)
        ),
        status=401,
        code="authentication_required",
    )

    assert error.detail == "A valid access token is required."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header",
    ["", "Basic abc", "Bearer", "Bearer one two", "bearer abc", " Bearer abc"],
)
async def test_malformed_bearer_header_is_rejected(
    rsa_signing_material: tuple[object, dict[str, PyJWK]],
    header: str,
) -> None:
    _, keys = rsa_signing_material

    await _expect_error(
        PlatformAdminAuthorizer(_verifier(keys)).authorize(
            authorization=header,
            session=MembershipSession(member=True),
        ),
        status=401,
        code="authentication_required",
    )


@pytest.mark.asyncio
async def test_expired_token_is_rejected(
    rsa_signing_material: tuple[object, dict[str, PyJWK]],
) -> None:
    signing_key, keys = rsa_signing_material
    access_jwt = _encode(
        signing_key,
        _claims(exp=datetime.now(UTC) - timedelta(seconds=1)),
    )

    await _expect_error(
        _verifier(keys).verify(access_jwt),
        status=401,
        code="authentication_required",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "https://attacker.invalid/auth/v1"),
        ("aud", "unexpected"),
        ("sub", "not-a-uuid"),
        ("role", "anon"),
        ("is_anonymous", True),
        ("session_id", "not-a-uuid"),
    ],
)
async def test_invalid_required_claim_is_rejected_as_authentication_failure(
    rsa_signing_material: tuple[object, dict[str, PyJWK]],
    claim: str,
    value: object,
) -> None:
    signing_key, keys = rsa_signing_material
    access_jwt = _encode(signing_key, _claims(**{claim: value}))

    await _expect_error(
        _verifier(keys).verify(access_jwt),
        status=401,
        code="authentication_required",
    )


@pytest.mark.asyncio
async def test_invalid_signature_and_unknown_jwks_key_fail_closed(
    rsa_signing_material: tuple[object, dict[str, PyJWK]],
) -> None:
    signing_key, keys = rsa_signing_material
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    invalid_signature = _encode(other_key, _claims())
    unknown_key = _encode(signing_key, _claims(), kid="unknown")

    for access_jwt in (invalid_signature, unknown_key):
        await _expect_error(
            _verifier(keys).verify(access_jwt),
            status=401,
            code="authentication_required",
        )


@pytest.mark.asyncio
async def test_algorithm_confusion_is_rejected_before_jwks_lookup() -> None:
    access_jwt = jwt.encode(
        _claims(),
        "not-a-real-secret",
        algorithm="HS256",
        headers={"kid": "rsa-test-key"},
    )

    await _expect_error(
        _verifier({}).verify(access_jwt),
        status=401,
        code="authentication_required",
    )


@pytest.mark.asyncio
async def test_es256_platform_admin_token_is_supported(
    ec_signing_material: tuple[object, dict[str, PyJWK]],
) -> None:
    signing_key, keys = ec_signing_material
    access_jwt = _encode(
        signing_key,
        _claims(),
        algorithm="ES256",
        kid="ec-test-key",
    )

    principal = await _verifier(keys).verify(access_jwt)

    assert principal == AdminPrincipal(user_id=USER_ID, session_id=SESSION_ID)


@pytest.mark.asyncio
async def test_user_metadata_role_spoof_cannot_authorize(
    rsa_signing_material: tuple[object, dict[str, PyJWK]],
) -> None:
    signing_key, keys = rsa_signing_material
    access_jwt = _encode(
        signing_key,
        _claims(
            app_metadata={},
            user_metadata={"platform_role": "platform_admin"},
        ),
    )

    await _expect_error(
        _verifier(keys).verify(access_jwt),
        status=403,
        code="platform_admin_required",
    )


@pytest.mark.asyncio
async def test_signed_role_without_platform_admin_row_is_forbidden(
    rsa_signing_material: tuple[object, dict[str, PyJWK]],
) -> None:
    signing_key, keys = rsa_signing_material
    access_jwt = _encode(signing_key, _claims())

    await _expect_error(
        PlatformAdminAuthorizer(_verifier(keys)).authorize(
            authorization=f"Bearer {access_jwt}",
            session=MembershipSession(member=False),
        ),
        status=403,
        code="platform_admin_required",
    )


@pytest.mark.asyncio
async def test_platform_admin_row_without_signed_role_is_forbidden(
    rsa_signing_material: tuple[object, dict[str, PyJWK]],
) -> None:
    signing_key, keys = rsa_signing_material
    access_jwt = _encode(signing_key, _claims(app_metadata={}))

    await _expect_error(
        PlatformAdminAuthorizer(_verifier(keys)).authorize(
            authorization=f"Bearer {access_jwt}",
            session=MembershipSession(member=True),
        ),
        status=403,
        code="platform_admin_required",
    )


@pytest.mark.asyncio
async def test_dual_authorized_admin_sets_constrained_role_and_returns_principal(
    rsa_signing_material: tuple[object, dict[str, PyJWK]],
) -> None:
    signing_key, keys = rsa_signing_material
    access_jwt = _encode(signing_key, _claims())
    session = MembershipSession(member=True)

    principal = await PlatformAdminAuthorizer(_verifier(keys)).authorize(
        authorization=f"Bearer {access_jwt}",
        session=session,
    )

    assert principal == AdminPrincipal(user_id=USER_ID, session_id=SESSION_ID)
    assert "SET LOCAL ROLE agents_factory_admin" in session.statements[0][0]
    assert "platform_admins" in session.statements[1][0]
    assert session.statements[1][1] == {"user_id": USER_ID}
