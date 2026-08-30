from __future__ import annotations

import asyncio
import base64
import json
import re
import socket
from collections.abc import Awaitable, Callable
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr, ValidationError, field_validator

from agents_factory.modules.integrations.google.base import InputModel
from agents_factory.modules.integrations.oauth import (
    AuthorizationGrant,
    ProviderFailure,
)
from agents_factory.modules.integrations.orders import OrderFailure
from agents_factory.modules.secrets.redaction import ResolvedSecret


def validate_store_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", parsed.hostname)
        or "." not in parsed.hostname
        or not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", parsed.path)
    ):
        raise ValueError("fixed HTTPS store URL required")
    return value


class WooCredential(InputModel):
    store_url: str
    consumer_key: SecretStr = Field(min_length=10, max_length=200, repr=False)
    consumer_secret: SecretStr = Field(min_length=10, max_length=200, repr=False)
    permission: Literal["read", "read_write"] = "read"

    _url = field_validator("store_url")(validate_store_url)


def decode(credential: ResolvedSecret) -> WooCredential:
    try:
        return WooCredential.model_validate_json(credential.reveal())
    except (ValidationError, ValueError):
        raise OrderFailure("invalid_credentials") from None


async def public_addresses(host: str) -> tuple[str, ...]:
    records = await asyncio.get_running_loop().getaddrinfo(
        host, 443, type=socket.SOCK_STREAM
    )
    return tuple(dict.fromkeys(str(record[4][0]) for record in records))


class WooHTTP:
    """Exact allowlist, public DNS/IP pinning, TLS SNI, no redirect/log/retry."""

    def __init__(
        self,
        allowed_stores: tuple[str, ...],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Callable[[str], Awaitable[tuple[str, ...]]] = public_addresses,
    ) -> None:
        self.allowed_stores = frozenset(
            validate_store_url(value) for value in allowed_stores
        )
        self.transport, self.resolver = transport, resolver

    async def json(
        self,
        credential: WooCredential,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: object = None,
    ) -> object:
        if credential.store_url not in self.allowed_stores or not re.fullmatch(
            r"orders(?:/[1-9][0-9]*(?:/notes)?)?", path
        ):
            raise OrderFailure("store_not_allowed")
        write = method != "GET"
        if write and credential.permission != "read_write":
            raise OrderFailure("permission_denied")
        hostname = urlsplit(credential.store_url).hostname
        assert hostname is not None
        try:
            addresses = await self.resolver(hostname)
        except (OSError, ValueError):
            raise OrderFailure("provider_unavailable") from None
        if not addresses or any(
            not ip_address(address).is_global for address in addresses
        ):
            raise OrderFailure("store_not_allowed")
        # The actual TCP destination is the verified IP, not a second DNS lookup.
        url = httpx.URL(credential.store_url + "/wp-json/wc/v3/" + path).copy_with(
            host=addresses[0]
        )
        pair = (
            credential.consumer_key.get_secret_value()
            + ":"
            + credential.consumer_secret.get_secret_value()
        )
        request = httpx.Request(
            method,
            url,
            params=params,
            json=body,
            headers={
                "Host": hostname,
                "Authorization": "Basic " + base64.b64encode(pair.encode()).decode(),
            },
            extensions={
                "sni_hostname": hostname,
                "timeout": {"connect": 5.0, "read": 20.0, "write": 20.0, "pool": 5.0},
            },
        )
        transport = self.transport or httpx.AsyncHTTPTransport(retries=0)
        response: httpx.Response | None = None
        try:
            response = await transport.handle_async_request(request)
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > 2 * 1024 * 1024:
                    raise OrderFailure("response_too_large", uncertain=write)
                raw.extend(chunk)
            status = response.status_code
            if not 200 <= status < 300:
                code = {
                    401: "authorization_revoked",
                    403: "permission_denied",
                    404: "order_not_found",
                    409: "conflict",
                    412: "stale_version",
                    429: "rate_limited",
                }.get(
                    status,
                    "provider_unavailable" if status >= 500 else "provider_rejected",
                )
                raise OrderFailure(code, uncertain=write and status >= 500)
            try:
                return json.loads(raw)
            except ValueError:
                raise OrderFailure("invalid_response", uncertain=write) from None
        except httpx.HTTPError:
            raise OrderFailure("provider_unavailable", uncertain=write) from None
        finally:
            if response is not None:
                await response.aclose()
            if self.transport is None:
                await transport.aclose()


class WooCredentialProvider:
    oauth = None

    def __init__(self, http: WooHTTP) -> None:
        self.http = http

    async def check_health(self, credential: ResolvedSecret) -> None:
        try:
            value = await self.http.json(
                decode(credential),
                "GET",
                "orders",
                params={"per_page": "1", "_fields": "id"},
            )
            if not isinstance(value, list):
                raise OrderFailure("invalid_response")
        except OrderFailure as error:
            if error.code == "authorization_revoked":
                raise ProviderFailure("authorization_revoked") from None
            if error.code in {
                "invalid_credentials",
                "store_not_allowed",
                "permission_denied",
            }:
                raise ProviderFailure("permission_denied") from None
            if error.code == "rate_limited":
                raise ProviderFailure("rate_limited") from None
            raise ProviderFailure("provider_unavailable") from None

    async def exchange(
        self, *, code: ResolvedSecret, verifier: ResolvedSecret
    ) -> AuthorizationGrant:
        raise ProviderFailure("permission_denied")

    async def refresh(self, credential: ResolvedSecret) -> AuthorizationGrant:
        raise ProviderFailure("permission_denied")

    async def revoke(self, credential: ResolvedSecret) -> None:
        # WC keys must be revoked in the store dashboard. IntegrationService has
        # already disabled local execution before calling this hook.
        return None
