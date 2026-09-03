from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from agents_factory.common.errors import DomainError
from agents_factory.common.security import AdminPrincipal, require_platform_admin
from agents_factory.modules.integrations.oauth import ProviderRegistry
from agents_factory.modules.integrations.router import (
    CompleteOAuthRequest,
    ConnectApiKeyRequest,
    router,
)


def test_secret_input_models_do_not_print_values_and_generic_rest_cannot_register() -> (
    None
):
    payload = ConnectApiKeyRequest(
        connector_name="woocommerce", credential="fixture-private-input"
    )
    callback = CompleteOAuthRequest(
        state="fixture-private-state", code="fixture-private-code"
    )
    assert "fixture-private" not in repr((payload, callback))
    assert "fixture-private" not in payload.model_dump_json()
    assert "fixture-private" not in callback.model_dump_json()
    with pytest.raises(ValueError):
        ProviderRegistry().register("generic_rest_api", object())


async def test_validation_errors_do_not_echo_credentials_or_authorization_codes() -> (
    None
):
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[require_platform_admin] = lambda: AdminPrincipal(
        uuid4(), uuid4()
    )

    @application.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={"code": error.code, "detail": error.detail},
        )

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://control.example.test",
    ) as client:
        response = await client.post(
            f"/admin/tenants/{uuid4()}/integrations/oauth/callback",
            json={
                "state": "short",
                "code": "fixture-private-code",
                "extra": "fixture-private-value",
            },
        )
    assert response.status_code == 422
    assert "fixture-private" not in response.text
    assert response.json()["code"] == "integration_request_invalid"
