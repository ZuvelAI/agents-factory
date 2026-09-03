from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.config import Settings
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.repository import SecretVault
from agents_factory.modules.whatsapp.account_service import (
    WhatsAppAccountRepository,
    WhatsAppAccountService,
    WhatsAppAccountSummary,
    WhatsAppDisconnectCoordinator,
)
from agents_factory.modules.whatsapp.contracts import (
    CoexistenceEligibility,
    WhatsAppHealthStatus,
    WhatsAppMode,
)
from agents_factory.modules.whatsapp.meta_provider import MetaEmbeddedSignupClient
from agents_factory.modules.whatsapp.signup_service import WhatsAppSignupService


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/whatsapp",
    tags=["platform-admin-whatsapp"],
)


class SignupStartResponse(BaseModel):
    app_id: str
    configuration_id: str
    redirect_uri: str
    state: str
    expires_at: datetime


class SignupCompleteRequest(BaseModel):
    state: str = Field(min_length=16, max_length=500)
    code: str = Field(min_length=1, max_length=2000)
    business_id: str = Field(min_length=1, max_length=200)
    waba_id: str = Field(min_length=1, max_length=200)
    phone_number_id: str = Field(min_length=1, max_length=200)
    mode: WhatsAppMode = "API_ONLY"


class WhatsAppAccountResponse(BaseModel):
    id: UUID
    business_id: str | None
    waba_id: str
    phone_number_id: str
    status: str
    mode: WhatsAppMode
    coexistence_eligibility: CoexistenceEligibility
    granted_scopes: tuple[str, ...]
    health_status: WhatsAppHealthStatus
    last_health_checked_at: datetime | None
    token_expires_at: datetime | None
    verified_at: datetime | None

    @classmethod
    def from_summary(cls, summary: WhatsAppAccountSummary) -> WhatsAppAccountResponse:
        return cls(
            id=summary.id,
            business_id=summary.business_id,
            waba_id=summary.waba_id,
            phone_number_id=summary.phone_number_id,
            status=summary.status,
            mode=summary.mode,
            coexistence_eligibility=summary.coexistence_eligibility,
            granted_scopes=summary.granted_scopes,
            health_status=summary.health_status,
            last_health_checked_at=summary.last_health_checked_at,
            token_expires_at=summary.token_expires_at,
            verified_at=summary.verified_at,
        )


@router.post(
    "/signup/start",
    response_model=SignupStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_embedded_signup(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> SignupStartResponse:
    settings, signup = _signup_services(request, session)
    started = await signup.start(
        context=_context(request, principal, tenant_id),
        admin_session_id=principal.session_id,
    )
    assert settings.meta_app_id is not None
    assert settings.meta_configuration_id is not None
    assert settings.meta_redirect_uri is not None
    return SignupStartResponse(
        app_id=settings.meta_app_id,
        configuration_id=settings.meta_configuration_id,
        redirect_uri=settings.meta_redirect_uri,
        state=started.state,
        expires_at=started.expires_at,
    )


@router.post(
    "/signup/complete",
    response_model=WhatsAppAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def complete_embedded_signup(
    tenant_id: UUID,
    payload: SignupCompleteRequest,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> WhatsAppAccountResponse:
    _settings, signup = _signup_services(request, session)
    connected = await signup.complete(
        context=_context(request, principal, tenant_id),
        admin_session_id=principal.session_id,
        state=payload.state,
        code=payload.code,
        business_id=payload.business_id,
        waba_id=payload.waba_id,
        phone_number_id=payload.phone_number_id,
        requested_mode=payload.mode,
    )
    return WhatsAppAccountResponse.from_summary(
        WhatsAppAccountSummary.from_account(connected)
    )


@router.get("", response_model=tuple[WhatsAppAccountResponse, ...])
async def list_whatsapp_accounts(
    tenant_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> tuple[WhatsAppAccountResponse, ...]:
    accounts = build_account_service(request, session)
    summaries = await accounts.list_summaries(
        context=_context(request, principal, tenant_id)
    )
    return tuple(WhatsAppAccountResponse.from_summary(item) for item in summaries)


@router.post(
    "/{account_id}/health",
    response_model=WhatsAppAccountResponse,
)
async def check_whatsapp_account_health(
    tenant_id: UUID,
    account_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> WhatsAppAccountResponse:
    accounts = build_account_service(request, session)
    summary = await accounts.check_health(
        context=_context(request, principal, tenant_id),
        account_id=account_id,
        checked_at=datetime.now(UTC),
    )
    return WhatsAppAccountResponse.from_summary(summary)


@router.post(
    "/{account_id}/revoke",
    response_model=WhatsAppAccountResponse,
)
async def revoke_whatsapp_account(
    tenant_id: UUID,
    account_id: UUID,
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> WhatsAppAccountResponse:
    accounts = build_account_service(request, session)
    summary = await accounts.revoke(
        context=_context(request, principal, tenant_id),
        account_id=account_id,
        revoked_at=datetime.now(UTC),
    )
    return WhatsAppAccountResponse.from_summary(summary)


def _signup_services(
    request: Request,
    session: AsyncSession,
) -> tuple[Settings, WhatsAppSignupService]:
    settings: Settings = request.app.state.settings
    app_id = settings.meta_app_id
    configuration_id = settings.meta_configuration_id
    redirect_uri = settings.meta_redirect_uri
    if app_id is None or configuration_id is None or redirect_uri is None:
        raise DomainError(
            type="https://agents-factory.dev/problems/meta-signup-not-configured",
            title="Meta Embedded Signup Not Configured",
            status=503,
            detail="Meta Embedded Signup is not configured for this environment.",
            code="meta_signup_not_configured",
        )
    repository, vault, provider = _service_dependencies(
        settings=settings,
        session=session,
    )
    return (
        settings,
        WhatsAppSignupService(
            repository=repository,
            vault=vault,
            provider=provider,
        ),
    )


def build_account_service(
    request: Request,
    session: AsyncSession,
) -> WhatsAppAccountService:
    settings: Settings = request.app.state.settings
    repository, vault, provider = _service_dependencies(
        settings=settings,
        session=session,
    )
    return WhatsAppAccountService(
        repository=repository,
        vault=vault,
        provider=provider,
        disconnect_executor=_disconnect_coordinator(
            settings=settings,
            session=session,
            provider=provider,
        ),
    )


def _service_dependencies(
    *, settings: Settings, session: AsyncSession
) -> tuple[WhatsAppAccountRepository, SecretVault, MetaEmbeddedSignupClient]:
    provider = MetaEmbeddedSignupClient(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        redirect_uri=settings.meta_redirect_uri,
        graph_api_base_url=settings.meta_graph_api_base_url,
    )
    bind = session.bind
    if not isinstance(bind, AsyncEngine):
        raise RuntimeError("WhatsApp account service requires an engine-bound session")
    repository = WhatsAppAccountRepository(
        session,
        state_session_factory=async_sessionmaker(bind, expire_on_commit=False),
    )
    key_provider = EnvironmentMasterKeyProvider(
        environment={"APP_MASTER_KEY": settings.app_master_key.get_secret_value()}
    )
    vault = SecretVault.for_session(session, key_provider=key_provider)
    return repository, vault, provider


def _disconnect_coordinator(
    *,
    settings: Settings,
    session: AsyncSession,
    provider: MetaEmbeddedSignupClient,
) -> WhatsAppDisconnectCoordinator:
    bind = session.bind
    if not isinstance(bind, AsyncEngine):
        raise RuntimeError(
            "WhatsApp disconnect coordinator requires an engine-bound session"
        )
    return WhatsAppDisconnectCoordinator(
        session_factory=async_sessionmaker(bind, expire_on_commit=False),
        key_provider=EnvironmentMasterKeyProvider(
            environment={"APP_MASTER_KEY": settings.app_master_key.get_secret_value()}
        ),
        provider=provider,
    )


def _context(
    request: Request, principal: AdminPrincipal, tenant_id: UUID
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        actor_id=principal.user_id,
        actor_type="platform_admin",
        correlation_id=request.state.correlation_id,
    )
