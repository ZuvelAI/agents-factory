from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx
from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal, PlatformAdmin
from agents_factory.config import Settings
from agents_factory.dependencies import TransactionSession
from agents_factory.database import set_tenant_context
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.repository import SecretVault
from agents_factory.modules.whatsapp.account_service import (
    DatabaseMetaAccessTokenResolver,
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
from agents_factory.modules.whatsapp.template_service import TemplateService
from agents_factory.modules.whatsapp.test_templates import simple_approved_templates


router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/whatsapp",
    tags=["platform-admin-whatsapp"],
)


class TestMessageRequest(BaseModel):
    recipient: str = Field(pattern=r"^[1-9][0-9]{7,14}$")
    template_name: str = Field(pattern=r"^[a-z0-9_]{1,512}$")
    language: str = Field(pattern=r"^[a-zA-Z_]{2,20}$")
    idempotency_key: UUID


def _test_error(detail: str) -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/whatsapp-test-unavailable",
        title="WhatsApp test unavailable", status=409,
        detail=detail, code="whatsapp_test_unavailable",
    )


@router.post("/{account_id}/test-templates")
async def load_test_templates(
    tenant_id: UUID, account_id: UUID, request: Request,
    principal: PlatformAdmin, session: TransactionSession,
) -> list[dict[str, str]]:
    context = _context(request, principal, tenant_id)
    settings: Settings = request.app.state.settings
    account = await WhatsAppAccountRepository(session).get(
        context=context, account_id=account_id,
    )
    if account is None or account.status != "active" or not account.waba_id.isdigit():
        raise _test_error("Conecta primero la cuenta de WhatsApp de este cliente.")
    resolver = DatabaseMetaAccessTokenResolver(
        session=session,
        key_provider=EnvironmentMasterKeyProvider(environment={
            "APP_MASTER_KEY": settings.app_master_key.get_secret_value(),
        }),
    )
    secret = await resolver.resolve(context=context, whatsapp_account_id=account_id)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{settings.meta_graph_api_base_url.rstrip('/')}/{account.waba_id}/message_templates",
                headers={"Authorization": f"Bearer {secret.reveal().decode('utf-8')}"},
                params={"fields": "id,name,language,status,category,components", "limit": "100"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise _test_error("No se pudieron consultar las plantillas en Meta. Revisa la conexión y sus permisos.") from None
    if not isinstance(payload, dict):
        raise _test_error("Meta devolvió una respuesta de plantillas inválida.")
    templates = simple_approved_templates(payload)
    await TemplateService(
        session_factory=request.app.state.database.session_factory, context=context,
    ).sync(whatsapp_account_id=account_id, templates=templates)
    return [{"name": t.name, "language": t.language} for t in templates]


@router.post("/{account_id}/test-messages", status_code=202)
async def queue_test_message(
    tenant_id: UUID, account_id: UUID, payload: TestMessageRequest,
    request: Request, principal: PlatformAdmin,
) -> dict[str, str]:
    context = _context(request, principal, tenant_id)
    message_id = await TemplateService(
        session_factory=request.app.state.database.session_factory, context=context,
    ).prepare_proactive(
        whatsapp_account_id=account_id, recipient_wa_id=payload.recipient,
        template_name=payload.template_name, language=payload.language,
        variables={}, idempotency_key=f"dashboard-test:{account_id}:{payload.idempotency_key}",
    )
    return {"id": str(message_id), "status": "PREPARED"}


@router.get("/{account_id}/test-messages/{message_id}")
async def test_message_status(
    tenant_id: UUID, account_id: UUID, message_id: UUID, request: Request,
    principal: PlatformAdmin, session: TransactionSession,
) -> dict[str, str | None]:
    await set_tenant_context(session, tenant_id)
    row = (await session.execute(text(
        "SELECT status, provider_message_id FROM public.outbound_messages "
        "WHERE tenant_id=:tenant AND whatsapp_account_id=:account AND id=:message"
    ), {"tenant": tenant_id, "account": account_id, "message": message_id})).mappings().one_or_none()
    if row is None:
        raise _test_error("No se encontró ese envío en este cliente.")
    return {"id": str(message_id), "status": row["status"], "provider_message_id": row["provider_message_id"]}


class SignupStartRequest(BaseModel):
    mode: WhatsAppMode = "API_ONLY"


def _require_available_signup_mode(mode: WhatsAppMode) -> None:
    # Release gate, not an eligibility verdict. Do not open a provider flow
    # until sync ingestion and human takeover can safely support real clients.
    if mode == "COEXISTENCE":
        raise DomainError(
            type="https://agents-factory.dev/problems/whatsapp-coexistence-not-ready",
            title="Coexistence pending enablement",
            status=409,
            detail="Coexistence synchronization and human takeover are not enabled yet.",
            code="whatsapp_coexistence_not_ready",
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
    payload: SignupStartRequest = SignupStartRequest(),
) -> SignupStartResponse:
    _require_available_signup_mode(payload.mode)
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
    _require_available_signup_mode(payload.mode)
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
    accounts = _account_service(request, session)
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
    accounts = _account_service(request, session)
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
    accounts = _account_service(request, session)
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


def _account_service(
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
        actor_type="customer" if getattr(request.state, "restricted_reviewer", False) else "platform_admin",
        correlation_id=request.state.correlation_id,
    )
