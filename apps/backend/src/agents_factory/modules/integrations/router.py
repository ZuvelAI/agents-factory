from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.config import Settings
from agents_factory.database import Database
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.integrations.meta_bridge import MetaConnectionBridge
from agents_factory.modules.integrations.models import (
    CatalogAvailability,
    CatalogEntry,
    ConnectionSummary,
    IntegrationError,
    SafeModel,
    V1_CONNECTION_NAMES,
)
from agents_factory.modules.integrations.oauth import OAuthStart, ProviderRegistry
from agents_factory.modules.integrations.registry import V1_CONNECTOR_CATALOG
from agents_factory.modules.integrations.service import IntegrationService
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.whatsapp.router import build_account_service


class _SafeValidationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def sanitized(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's default validation response includes the original input.
                raise IntegrationError(
                    "integration_request_invalid", status=422
                ) from None

        return sanitized


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/integrations",
    tags=["platform-admin-integrations"],
    route_class=_SafeValidationRoute,
)


class StartOAuthRequest(SafeModel):
    connector_name: str = Field(min_length=1, max_length=100)
    scopes: tuple[str, ...] = Field(min_length=1, max_length=20)
    connection_id: UUID | None = None


class CompleteOAuthRequest(SafeModel):
    state: SecretStr = Field(min_length=16, max_length=500, repr=False)
    code: SecretStr = Field(min_length=1, max_length=4096, repr=False)


class ConnectApiKeyRequest(SafeModel):
    connector_name: str = Field(min_length=1, max_length=100)
    credential: SecretStr = Field(min_length=1, max_length=32768, repr=False)
    connection_id: UUID | None = None


@router.get("/connections", response_model=tuple[ConnectionSummary, ...])
async def list_connections(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> tuple[ConnectionSummary, ...]:
    context = _context(request, principal, tenant_id)
    return (
        *await _service(request).list(context=context),
        *await _meta(request, session).list(context),
    )


@router.get("/catalog", response_model=tuple[CatalogEntry, ...])
async def integration_catalog(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> tuple[CatalogEntry, ...]:
    connections = await list_connections(tenant_id, request, principal, session)
    providers: ProviderRegistry = request.app.state.integration_providers
    manifests = {item.stable_name: item for item in V1_CONNECTOR_CATALOG.list()}
    entries: list[CatalogEntry] = []
    names = {*V1_CONNECTION_NAMES, *manifests, "meta_whatsapp"}
    for name in sorted(names):
        manifest = manifests.get(name)
        is_meta = name == "meta_whatsapp"
        provider = providers.get(name) if providers.contains(name) else None
        enabled = is_meta or (
            provider is not None
            and manifest is not None
            and manifest.availability == "AVAILABLE"
        )
        availability: CatalogAvailability = (
            "AVAILABLE"
            if enabled
            else "SETUP_REQUIRED"
            if manifest is not None and manifest.availability == "AVAILABLE"
            else "COMING_LATER"
        )
        entries.append(
            CatalogEntry(
                connector_name=name,
                display_name=manifest.display_name if manifest else name,
                available=enabled,
                availability=availability,
                auth_kind=(
                    "META_EMBEDDED"
                    if is_meta
                    else "OAUTH2"
                    if provider is not None and provider.oauth is not None
                    else "API_KEY"
                    if provider is not None
                    else None
                ),
                required_scopes=(
                    tuple(sorted(provider.oauth.allowed_scopes))
                    if provider is not None and provider.oauth is not None
                    else ()
                ),
                supported_operations=manifest.supported_operations if manifest else (),
                connections=tuple(c for c in connections if c.connector_name == name),
                note=(
                    "Connect or reconnect through Meta Embedded Signup."
                    if is_meta
                    else "Deployment provider credentials are not configured yet."
                    if availability == "SETUP_REQUIRED"
                    else manifest.availability_note
                    if manifest
                    else "Provider adapter not configured yet."
                ),
            )
        )
    return tuple(entries)


@router.post("/oauth/start", response_model=OAuthStart, status_code=201)
async def start_oauth(
    tenant_id: UUID,
    payload: StartOAuthRequest,
    request: Request,
    principal: PlatformAdmin,
) -> OAuthStart:
    return await _service(request).start_oauth(
        context=_context(request, principal, tenant_id),
        admin_session_id=principal.session_id,
        connector_name=payload.connector_name,
        scopes=payload.scopes,
        connection_id=payload.connection_id,
    )


@router.post("/oauth/callback", response_model=ConnectionSummary)
async def complete_oauth(
    tenant_id: UUID,
    payload: CompleteOAuthRequest,
    request: Request,
    principal: PlatformAdmin,
) -> ConnectionSummary:
    return await _service(request).complete_oauth(
        context=_context(request, principal, tenant_id),
        admin_session_id=principal.session_id,
        state=payload.state.get_secret_value(),
        code=ResolvedSecret(payload.code.get_secret_value().encode()),
    )


@router.post("/api-key", response_model=ConnectionSummary, status_code=201)
async def connect_api_key(
    tenant_id: UUID,
    payload: ConnectApiKeyRequest,
    request: Request,
    principal: PlatformAdmin,
) -> ConnectionSummary:
    return await _service(request).connect_api_key(
        context=_context(request, principal, tenant_id),
        connector_name=payload.connector_name,
        credential=ResolvedSecret(payload.credential.get_secret_value().encode()),
        connection_id=payload.connection_id,
    )


@router.post("/connections/{connection_id}/refresh", response_model=ConnectionSummary)
async def refresh_connection(
    tenant_id: UUID, connection_id: UUID, request: Request, principal: PlatformAdmin
) -> ConnectionSummary:
    return await _service(request).refresh(
        context=_context(request, principal, tenant_id), connection_id=connection_id
    )


@router.post("/connections/{connection_id}/health", response_model=ConnectionSummary)
async def check_connection_health(
    tenant_id: UUID,
    connection_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> ConnectionSummary:
    context = _context(request, principal, tenant_id)
    meta = _meta(request, session)
    if any(c.id == connection_id for c in await meta.list(context)):
        return await meta.check_health(context, connection_id)
    return await _service(request).check_health(
        context=context, connection_id=connection_id
    )


@router.post("/connections/{connection_id}/revoke", response_model=ConnectionSummary)
async def revoke_connection(
    tenant_id: UUID,
    connection_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> ConnectionSummary:
    context = _context(request, principal, tenant_id)
    meta = _meta(request, session)
    if any(c.id == connection_id for c in await meta.list(context)):
        return await meta.revoke(context, connection_id)
    return await _service(request).revoke(context=context, connection_id=connection_id)


def _service(request: Request) -> IntegrationService:
    settings: Settings = request.app.state.settings
    database: Database = request.app.state.database
    return IntegrationService(
        sessions=database.session_factory,
        key_provider=EnvironmentMasterKeyProvider(
            environment={
                "APP_MASTER_KEY": settings.app_master_key.get_secret_value(),
                "APP_MASTER_KEY_VERSION": str(settings.app_master_key_version),
            }
        ),
        providers=request.app.state.integration_providers,
    )


def _meta(request: Request, session: AsyncSession) -> MetaConnectionBridge:
    return MetaConnectionBridge(build_account_service(request, session))


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )
