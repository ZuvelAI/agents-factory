import pytest
from types import SimpleNamespace
from uuid import UUID, uuid4
from unittest.mock import AsyncMock
import httpx
from pydantic import ValidationError

from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal
from agents_factory.config import Settings
from agents_factory.dependencies import get_transaction
from agents_factory.main import create_app
from agents_factory.modules.whatsapp import router as signup_router
from agents_factory.modules.whatsapp.router import (
    SignupStartRequest,
    _require_available_signup_mode,
)


def test_exclusive_mode_remains_available() -> None:
    _require_available_signup_mode("API_ONLY")


def test_coexistence_is_not_silently_converted_or_enabled() -> None:
    with pytest.raises(DomainError) as error:
        _require_available_signup_mode("COEXISTENCE")
    assert error.value.code == "whatsapp_coexistence_not_ready"


PILOT_TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = UUID("22222222-2222-4222-8222-222222222222")


def pilot_settings() -> Settings:
    return Settings.model_construct(
        coexistence_pilot_tenant_id=PILOT_TENANT,
        coexistence_pilot_phone_digits="15550123456",
    )


def test_pilot_signup_is_allowed_only_for_the_configured_tenant() -> None:
    _require_available_signup_mode(
        "COEXISTENCE", tenant_id=PILOT_TENANT, settings=pilot_settings()
    )
    with pytest.raises(DomainError) as error:
        _require_available_signup_mode(
            "COEXISTENCE", tenant_id=OTHER_TENANT, settings=pilot_settings()
        )
    assert error.value.code == "whatsapp_coexistence_not_ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["start", "complete"])
async def test_closed_pilot_rejects_start_and_old_callback_before_provider_use(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    def unexpected_provider(*args: object) -> None:
        pytest.fail("closed pilot reached the provider")

    monkeypatch.setattr(signup_router, "_signup_services", unexpected_provider)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=Settings.model_construct()))
    )
    principal = AdminPrincipal(user_id=uuid4(), session_id=uuid4())
    with pytest.raises(DomainError) as error:
        if phase == "start":
            await signup_router.start_embedded_signup(
                PILOT_TENANT,
                request,
                principal,
                object(),
                SignupStartRequest(mode="COEXISTENCE"),
            )
        else:
            await signup_router.complete_embedded_signup(
                PILOT_TENANT,
                signup_router.SignupCompleteRequest(
                    state="x" * 32, code="code", waba_id="123", mode="COEXISTENCE"
                ),
                request,
                principal,
                object(),
            )
    assert error.value.code == "whatsapp_coexistence_not_ready"


@pytest.mark.asyncio
async def test_availability_exposes_only_the_tenant_scoped_permission() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=pilot_settings()))
    )
    principal = AdminPrincipal(user_id=uuid4(), session_id=uuid4())
    enabled = await signup_router.signup_availability(PILOT_TENANT, request, principal)
    disabled = await signup_router.signup_availability(OTHER_TENANT, request, principal)
    assert enabled.model_dump() == {"coexistence_enabled": True}
    assert disabled.model_dump() == {"coexistence_enabled": False}


@pytest.mark.asyncio
async def test_completion_passes_only_the_server_owned_number_to_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = pilot_settings()
    signup = SimpleNamespace(
        complete=AsyncMock(
            side_effect=DomainError(
                type="https://example.invalid/provider-failure",
                title="Provider failure",
                status=409,
                detail="Synthetic provider rejection",
                code="synthetic_provider_rejection",
            )
        )
    )
    monkeypatch.setattr(
        signup_router, "_signup_services", lambda *_: (settings, signup)
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        state=SimpleNamespace(correlation_id=uuid4()),
    )
    with pytest.raises(DomainError) as error:
        await signup_router.complete_embedded_signup(
            PILOT_TENANT,
            signup_router.SignupCompleteRequest(
                state="x" * 32, code="code", waba_id="123", mode="COEXISTENCE"
            ),
            request,
            AdminPrincipal(user_id=uuid4(), session_id=uuid4()),
            object(),
        )
    assert error.value.code == "synthetic_provider_rejection"
    assert signup.complete.await_args.kwargs["expected_phone_digits"] == "15550123456"


@pytest.mark.asyncio
async def test_pilot_availability_requires_platform_admin_authentication() -> None:
    app = create_app()
    app.state.settings = pilot_settings()
    from agents_factory.common.security import PlatformAdminAuthorizer

    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(AsyncMock())

    async def transaction():
        yield AsyncMock()

    app.dependency_overrides[get_transaction] = transaction
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/admin/tenants/{PILOT_TENANT}/whatsapp/signup/availability"
        )
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_unknown_modes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SignupStartRequest(mode="automatic")


def test_coexistence_callback_accepts_waba_only_but_api_only_requires_all_assets() -> (
    None
):
    from agents_factory.modules.whatsapp.router import SignupCompleteRequest

    payload = {"state": "x" * 32, "code": "code", "waba_id": "123"}
    callback = SignupCompleteRequest(**payload, mode="COEXISTENCE")
    assert callback.business_id is None
    assert callback.phone_number_id is None
    with pytest.raises(ValidationError):
        SignupCompleteRequest(**payload, mode="API_ONLY")
