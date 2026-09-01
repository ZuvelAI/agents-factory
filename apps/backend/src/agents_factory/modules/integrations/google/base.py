from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Annotated, ClassVar, Generic, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agents_factory.modules.integrations.contracts import (
    ConnectorManifest,
    ConnectorRequest,
    ConnectorResult,
)
from agents_factory.modules.integrations.usage import record_external_request
from agents_factory.modules.secrets.redaction import ResolvedSecret


SCOPE_ROOT = "https://www.googleapis.com/auth/"
ResourceId = Annotated[
    str,
    Field(min_length=1, max_length=254, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_@.+\-]*$"),
]
logger = logging.getLogger(__name__)
_HOSTS = frozenset(
    {
        "www.googleapis.com",
        "gmail.googleapis.com",
        "sheets.googleapis.com",
        "oauth2.googleapis.com",
    }
)


class InputModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, allow_inf_nan=False
    )


class GoogleFailure(Exception):
    def __init__(self, code: str, *, uncertain: bool = False) -> None:
        self.code, self.uncertain = code, uncertain
        super().__init__(code)


class GoogleHTTP:
    """Fixed-origin transport, bounded responses, no redirects or automatic retries.

    Use the transport directly: AsyncClient's INFO request logging would expose
    tokeninfo's query credential. No URLs, headers, bodies or provider errors are logged.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def request(
        self,
        method: str,
        url: str,
        *,
        access: ResolvedSecret | None = None,
        params: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
        body: object = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        write: bool = False,
        limit: int = 2 * 1024 * 1024,
    ) -> bytes:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _HOSTS
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.query
            or parsed.fragment
        ):
            raise GoogleFailure("invalid_endpoint")
        request_headers = dict(headers or {})
        if access is not None:
            request_headers["Authorization"] = "Bearer " + access.reveal().decode()
        request = httpx.Request(
            method,
            url,
            headers=request_headers,
            params=params,
            data=form,
            json=body,
            content=content,
            extensions={
                "timeout": {"connect": 5.0, "read": 20.0, "write": 20.0, "pool": 5.0}
            },
        )
        transport = self._transport or httpx.AsyncHTTPTransport(retries=0)
        response: httpx.Response | None = None
        started = monotonic()
        try:
            response = await transport.handle_async_request(request)
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                if len(chunks) + len(chunk) > limit:
                    raise GoogleFailure("response_too_large", uncertain=write)
                chunks.extend(chunk)
            if not 200 <= response.status_code < 300:
                _raise_http_failure(response.status_code, bytes(chunks), write=write)
            return bytes(chunks)
        except httpx.HTTPError:
            raise GoogleFailure("provider_unavailable", uncertain=write) from None
        finally:
            if response is not None:
                await response.aclose()
            if self._transport is None:
                await transport.aclose()
            await record_external_request(
                provider="google",
                occurrence_known=response is not None,
                latency_ms=round((monotonic() - started) * 1000),
            )

    async def json(
        self,
        method: str,
        url: str,
        *,
        access: ResolvedSecret | None = None,
        params: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
        body: object = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        write: bool = False,
    ) -> dict[str, object]:
        raw = await self.request(
            method,
            url,
            access=access,
            params=params,
            form=form,
            body=body,
            content=content,
            headers=headers,
            write=write,
        )
        try:
            result: object = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, TypeError):
            raise GoogleFailure("invalid_response", uncertain=write) from None


def _raise_http_failure(status: int, raw: bytes, *, write: bool) -> None:
    # Inspect only code/reason; never return or log the provider's diagnostic text.
    reason = ""
    try:
        payload = json.loads(raw).get("error", "")
        if isinstance(payload, str):
            reason = payload
        elif isinstance(payload, dict):
            reason = payload.get("errors", [{}])[0].get("reason", "")
    except (ValueError, AttributeError, IndexError, TypeError):
        pass
    if not isinstance(reason, str):
        reason = ""
    if status == 401 or reason in {"invalid_grant", "invalid_token"}:
        code = "authorization_revoked"
    elif status == 429 or reason in {"rateLimitExceeded", "userRateLimitExceeded"}:
        code = "rate_limited"
    else:
        code = {
            403: "permission_denied",
            404: "not_found",
            409: "conflict",
            412: "stale_version",
        }.get(status, "provider_unavailable" if status >= 500 else "provider_rejected")
    raise GoogleFailure(code, uncertain=write and status >= 500)


@dataclass(frozen=True)
class GoogleBinding:
    """Trusted backend configuration, never built from model-supplied arguments."""

    tenant_id: UUID
    binding_id: UUID
    operations: frozenset[str]


ResourceT = TypeVar("ResourceT", bound=InputModel)


class GoogleConnector(Generic[ResourceT]):
    manifest: ClassVar[ConnectorManifest]
    operation_scopes: ClassVar[dict[str, frozenset[str]]]
    write_operations: ClassVar[frozenset[str]] = frozenset()

    def __init__(
        self,
        *,
        binding: GoogleBinding,
        resource: ResourceT,
        credential: ResolvedSecret,
        http: GoogleHTTP,
    ) -> None:
        # This object lives only within the backend credential lease.
        from agents_factory.modules.integrations.google.auth import decode_credential

        self.binding, self.http = binding, http
        self.resource = resource
        self._credential = decode_credential(credential)

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        started = monotonic()
        write = request.operation in self.write_operations
        try:
            if (
                request.tenant_id != self.binding.tenant_id
                or request.binding_id != self.binding.binding_id
            ):
                raise GoogleFailure("binding_mismatch")
            if (
                request.operation not in self.binding.operations
                or request.operation not in self.manifest.supported_operations
            ):
                raise GoogleFailure("operation_not_allowed")
            self._credential.require(self.operation_scopes[request.operation])
            if write and request.idempotency_key is None:
                raise GoogleFailure("idempotency_key_required")
            data = await self._execute(request)
            result = ConnectorResult(
                operation=request.operation, status="SUCCEEDED", data=data
            )
        except ValidationError:
            result = ConnectorResult(
                operation=request.operation,
                status="REJECTED",
                error_code="invalid_arguments",
            )
        except GoogleFailure as error:
            rejected = error.code in {
                "binding_mismatch",
                "operation_not_allowed",
                "insufficient_scope",
                "invalid_arguments",
                "resource_not_allowed",
                "idempotency_key_required",
                "mime_not_allowed",
                "file_too_large",
                "header_mapping_mismatch",
            }
            result = ConnectorResult(
                operation=request.operation,
                status="UNCERTAIN"
                if error.uncertain
                else "REJECTED"
                if rejected
                else "FAILED",
                error_code=error.code,
            )
        logger.info(
            "google.operation",
            extra={
                "connector": self.manifest.stable_name,
                "operation": request.operation,
                "tenant_id": str(request.tenant_id),
                "binding_id": str(request.binding_id),
                "status": result.status,
                "error_code": result.error_code,
                "duration_ms": round((monotonic() - started) * 1000),
            },
        )
        return result

    async def _execute(self, request: ConnectorRequest) -> dict[str, object]:
        raise NotImplementedError

    @property
    def access(self) -> ResolvedSecret:
        return self._credential.access


def manifest(
    name: str, display: str, operations: tuple[str, ...], entry: str
) -> ConnectorManifest:
    return ConnectorManifest(
        stable_name=name,
        display_name=display,
        version="1.0.0",
        availability="AVAILABLE",
        supported_operations=operations,
        availability_note="Requires a connected, scoped credential and approved resource binding.",
        executable_entry_point=f"agents_factory.modules.integrations.google.{entry}",
    )


def response_string(
    payload: Mapping[str, object], key: str, *, write: bool = False
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GoogleFailure("invalid_response", uncertain=write)
    return value
