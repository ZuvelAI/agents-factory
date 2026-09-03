from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, Field, SecretStr, ValidationError

from agents_factory.modules.integrations.google.base import (
    GoogleFailure,
    GoogleHTTP,
    InputModel,
    SCOPE_ROOT,
)
from agents_factory.modules.integrations.oauth import (
    AuthorizationGrant,
    OAuthConfiguration,
    ProviderFailure,
    ProviderFailureCode,
    ProviderRegistry,
)
from agents_factory.modules.secrets.redaction import ResolvedSecret


GoogleProduct = Literal["google_calendar", "gmail", "google_drive", "google_sheets"]
CALENDAR_READ = SCOPE_ROOT + "calendar.events.readonly"
CALENDAR_WRITE = SCOPE_ROOT + "calendar.events"
CALENDAR_BUSY = SCOPE_ROOT + "calendar.events.freebusy"
GMAIL_SEND = SCOPE_ROOT + "gmail.send"
DRIVE_FILE = SCOPE_ROOT + "drive.file"
SHEETS_READ = SCOPE_ROOT + "spreadsheets.readonly"
SHEETS_WRITE = SCOPE_ROOT + "spreadsheets"
PRODUCT_SCOPES: dict[str, frozenset[str]] = {
    "google_calendar": frozenset({CALENDAR_READ, CALENDAR_WRITE, CALENDAR_BUSY}),
    "gmail": frozenset({GMAIL_SEND}),
    "google_drive": frozenset({DRIVE_FILE}),
    "google_sheets": frozenset({SHEETS_READ, SHEETS_WRITE}),
}


class GoogleClientConfiguration(InputModel):
    client_id: str = Field(min_length=1, max_length=500)
    client_credential: SecretStr = Field(min_length=1, alias="client_secret")
    redirect_uri: str


class _StoredCredential(InputModel):
    access_token: SecretStr = Field(min_length=1)
    refresh_token: SecretStr = Field(min_length=1)
    scopes: tuple[str, ...]
    expires_at: AwareDatetime


@dataclass(frozen=True)
class GoogleCredential:
    access: ResolvedSecret = field(repr=False)
    refresh: ResolvedSecret = field(repr=False)
    scopes: frozenset[str]
    expires_at: datetime

    def require(self, alternatives: frozenset[str]) -> None:
        if self.expires_at <= datetime.now(UTC):
            raise GoogleFailure("credentials_expired")
        if not self.scopes.intersection(alternatives):
            raise GoogleFailure("insufficient_scope")


def decode_credential(value: ResolvedSecret) -> GoogleCredential:
    try:
        stored = _StoredCredential.model_validate_json(value.reveal())
    except ValidationError:
        raise GoogleFailure("invalid_credentials") from None
    return GoogleCredential(
        ResolvedSecret(stored.access_token.get_secret_value().encode()),
        ResolvedSecret(stored.refresh_token.get_secret_value().encode()),
        frozenset(stored.scopes),
        stored.expires_at,
    )


class GoogleOAuthProvider:
    def __init__(
        self,
        *,
        product: GoogleProduct,
        configuration: GoogleClientConfiguration,
        http: GoogleHTTP,
    ) -> None:
        self.product, self._configuration, self._http = product, configuration, http
        self.oauth = OAuthConfiguration(
            authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
            client_id=configuration.client_id,
            redirect_uri=configuration.redirect_uri,
            allowed_scopes=PRODUCT_SCOPES[product],
        )

    async def exchange(
        self, *, code: ResolvedSecret, verifier: ResolvedSecret
    ) -> AuthorizationGrant:
        return await self._grant(
            {
                "grant_type": "authorization_code",
                "code": code.reveal().decode(),
                "code_verifier": verifier.reveal().decode(),
                "redirect_uri": self._configuration.redirect_uri,
            }
        )

    async def refresh(self, credential: ResolvedSecret) -> AuthorizationGrant:
        prior = decode_credential(credential)
        return await self._grant(
            {
                "grant_type": "refresh_token",
                "refresh_token": prior.refresh.reveal().decode(),
            },
            prior=prior,
        )

    async def _grant(
        self, fields: dict[str, str], *, prior: GoogleCredential | None = None
    ) -> AuthorizationGrant:
        fields.update(
            {
                "client_id": self._configuration.client_id,
                "client_secret": self._configuration.client_credential.get_secret_value(),
            }
        )
        try:
            payload = await self._http.json(
                "POST", "https://oauth2.googleapis.com/token", form=fields
            )
            access_value = payload["access_token"]
            refresh_value = payload.get(
                "refresh_token", prior.refresh.reveal().decode() if prior else None
            )
            scope_value = payload.get(
                "scope", " ".join(sorted(prior.scopes)) if prior else ""
            )
            duration = payload["expires_in"]
            kind = payload.get("token_type", "Bearer")
            if (
                not isinstance(access_value, str)
                or not access_value
                or not isinstance(refresh_value, str)
                or not refresh_value
                or not isinstance(scope_value, str)
                or not scope_value
                or type(duration) is not int
                or not 0 < duration <= 86400
                or not isinstance(kind, str)
                or kind.lower() != "bearer"
            ):
                raise ValueError
            scopes = tuple(sorted(set(scope_value.split())))
            if not set(scopes).issubset(self.oauth.allowed_scopes) or (
                prior is not None and set(scopes) != prior.scopes
            ):
                raise ProviderFailure("permission_denied")
            expiry = datetime.now(UTC) + timedelta(seconds=duration)
            # Explicit serialization exists ONLY at the encrypted-vault boundary.
            opaque = json.dumps(
                {
                    "access_token": access_value,
                    "refresh_token": refresh_value,
                    "scopes": scopes,
                    "expires_at": expiry.isoformat(),
                }
            ).encode()
            return AuthorizationGrant(
                credential=ResolvedSecret(opaque),
                granted_scopes=scopes,
                expires_at=expiry,
            )
        except GoogleFailure as error:
            raise _provider_failure(error) from None
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ProviderFailure("invalid_response") from None

    async def revoke(self, credential: ResolvedSecret) -> None:
        try:
            await self._http.request(
                "POST",
                "https://oauth2.googleapis.com/revoke",
                form={"token": decode_credential(credential).refresh.reveal().decode()},
            )
        except GoogleFailure as error:
            if error.code != "authorization_revoked":
                raise _provider_failure(error) from None

    async def check_health(self, credential: ResolvedSecret) -> None:
        try:
            value = decode_credential(credential)
            value.require(self.oauth.allowed_scopes)
            # Official discovery specifies POST + query. Direct transport suppresses
            # request URL logging. No Gmail read/profile scope is needed.
            payload = await self._http.json(
                "POST",
                "https://www.googleapis.com/oauth2/v2/tokeninfo",
                params={"access_token": value.access.reveal().decode()},
            )
            scopes = payload.get("scope")
            if (
                not isinstance(scopes, str)
                or set(scopes.split()) != value.scopes
                or not value.scopes.issubset(self.oauth.allowed_scopes)
                or payload.get("issued_to") != self.oauth.client_id
            ):
                raise ProviderFailure("permission_denied")
            if int(str(payload.get("expires_in", "0"))) <= 0:
                raise ProviderFailure("authorization_revoked")
        except GoogleFailure as error:
            raise _provider_failure(error) from None
        except (TypeError, ValueError):
            raise ProviderFailure("invalid_response") from None


def _provider_failure(error: GoogleFailure) -> ProviderFailure:
    code: ProviderFailureCode = "provider_unavailable"
    if error.code in {"credentials_expired", "authorization_revoked"}:
        code = "authorization_revoked"
    elif error.code in {"permission_denied", "insufficient_scope"}:
        code = "permission_denied"
    elif error.code == "rate_limited":
        code = "rate_limited"
    elif error.code in {"invalid_credentials", "invalid_response"}:
        code = "invalid_response"
    return ProviderFailure(code)


def configured_google_providers(configuration: SecretStr | None) -> ProviderRegistry:
    registry = ProviderRegistry()
    if configuration is None:
        return registry
    try:
        clients = json.loads(configuration.get_secret_value())
        if not isinstance(clients, dict) or set(clients) - PRODUCT_SCOPES.keys():
            raise ValueError
        for product, payload in clients.items():
            client = GoogleClientConfiguration.model_validate(payload)
            # Pydantic validates the literal without exposing configuration contents.
            if product not in PRODUCT_SCOPES:
                raise ValueError
            registry.register(
                product,
                GoogleOAuthProvider(
                    product=product, configuration=client, http=GoogleHTTP()
                ),
            )
    except (ValueError, TypeError):
        raise ValueError("Invalid GOOGLE_OAUTH_CLIENTS configuration") from None
    return registry
