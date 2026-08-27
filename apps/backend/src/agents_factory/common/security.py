from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, cast
from uuid import UUID

import jwt
from fastapi import Depends, Header, Request
from jwt import PyJWK, PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.errors import DomainError
from agents_factory.dependencies import TransactionSession


ALLOWED_SUPABASE_ALGORITHMS = frozenset({"ES256", "RS256"})


def _authentication_error() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/authentication-required",
        title="Authentication Required",
        status=401,
        detail="A valid access token is required.",
        code="authentication_required",
    )


def _authorization_error() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/platform-admin-required",
        title="Platform Admin Required",
        status=403,
        detail="Platform administrator access is required.",
        code="platform_admin_required",
    )


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    user_id: UUID
    session_id: UUID


class SigningKeyClient(Protocol):
    def get_signing_key_from_jwt(self, access_jwt: str) -> PyJWK: ...


class TokenVerifier(Protocol):
    async def verify(self, access_jwt: str) -> AdminPrincipal: ...


class JwksTokenVerifier:
    """Verify Supabase access tokens with cached asymmetric JWKS keys."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_client: SigningKeyClient | None = None,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._jwks_client = jwks_client or PyJWKClient(
            f"{self._issuer}/.well-known/jwks.json",
            cache_keys=True,
            max_cached_keys=16,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )

    async def verify(self, access_jwt: str) -> AdminPrincipal:
        try:
            return await asyncio.to_thread(self._verify_sync, access_jwt)
        except DomainError:
            raise
        except (InvalidTokenError, PyJWKClientError, ValueError, TypeError):
            raise _authentication_error() from None

    def _verify_sync(self, access_jwt: str) -> AdminPrincipal:
        header = jwt.get_unverified_header(access_jwt)
        algorithm = header.get("alg")
        key_id = header.get("kid")
        if algorithm not in ALLOWED_SUPABASE_ALGORITHMS:
            raise _authentication_error()
        if not isinstance(key_id, str) or not key_id.strip():
            raise _authentication_error()

        signing_key = self._jwks_client.get_signing_key_from_jwt(access_jwt)
        claims = jwt.decode(
            access_jwt,
            key=signing_key.key,
            algorithms=[cast(str, algorithm)],
            audience=self._audience,
            issuer=self._issuer,
            options={
                "require": [
                    "aud",
                    "exp",
                    "iss",
                    "is_anonymous",
                    "role",
                    "session_id",
                    "sub",
                ]
            },
        )
        return self._principal_from_claims(claims)

    @staticmethod
    def _principal_from_claims(claims: dict[str, Any]) -> AdminPrincipal:
        if claims.get("role") != "authenticated":
            raise _authentication_error()
        if claims.get("is_anonymous") is not False:
            raise _authentication_error()

        try:
            user_id = UUID(cast(str, claims["sub"]))
            session_id = UUID(cast(str, claims["session_id"]))
        except (KeyError, TypeError, ValueError):
            raise _authentication_error() from None

        app_metadata = claims.get("app_metadata")
        if not isinstance(app_metadata, dict):
            raise _authorization_error()
        if app_metadata.get("platform_role") != "platform_admin":
            raise _authorization_error()
        return AdminPrincipal(user_id=user_id, session_id=session_id)


class PlatformAdminAuthorizer:
    def __init__(self, verifier: TokenVerifier) -> None:
        self._verifier = verifier

    async def authorize(
        self,
        *,
        authorization: str | None,
        session: AsyncSession,
    ) -> AdminPrincipal:
        access_jwt = _parse_bearer_token(authorization)
        principal = await self._verifier.verify(access_jwt)

        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        membership = await session.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM public.platform_admins WHERE user_id = :user_id"
                ")"
            ),
            {"user_id": principal.user_id},
        )
        if membership.scalar_one() is not True:
            raise _authorization_error()
        return principal


def _parse_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise _authentication_error()
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1]:
        raise _authentication_error()
    return parts[1]


async def require_platform_admin(
    request: Request,
    session: TransactionSession,
    authorization: Annotated[str | None, Header()] = None,
) -> AdminPrincipal:
    authorizer: PlatformAdminAuthorizer = request.app.state.platform_admin_authorizer
    return await authorizer.authorize(
        authorization=authorization,
        session=session,
    )


PlatformAdmin = Annotated[AdminPrincipal, Depends(require_platform_admin)]
