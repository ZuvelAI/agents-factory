from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from agents_factory.common.context import TenantContext
from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.whatsapp.contracts import (
    OutboundTemplateRequest,
    OutboundTextRequest,
)
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider


TENANT_ID = UUID("019c2000-0000-7000-8000-000000000001")
ACCOUNT_ID = UUID("019c2000-0000-7000-8000-000000000002")
CORRELATION_ID = UUID("019c2000-0000-7000-8000-000000000003")
GRAPH_API_BASE_URL = "https://graph.facebook.com/v25.0"
ACCESS_TOKEN = b"meta-test-access-token"


class StaticAccessTokenResolver:
    async def resolve(
        self,
        *,
        context: TenantContext,
        whatsapp_account_id: UUID,
    ) -> ResolvedSecret:
        assert context.tenant_id == TENANT_ID
        assert whatsapp_account_id == ACCOUNT_ID
        return ResolvedSecret(ACCESS_TOKEN)


def _context() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        actor_id=None,
        actor_type="system",
        correlation_id=CORRELATION_ID,
    )


@pytest.mark.asyncio
async def test_meta_provider_sends_text_with_backend_resolved_credential() -> None:
    captured: list[httpx.Request] = []

    def accept(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.1"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(accept)) as client:
        provider = MetaCloudApiProvider(
            app_secret=SecretStr("meta-app-secret"),
            access_tokens=StaticAccessTokenResolver(),
            http_client=client,
            graph_api_base_url=GRAPH_API_BASE_URL,
        )
        result = await provider.send_text(
            OutboundTextRequest(
                context=_context(),
                whatsapp_account_id=ACCOUNT_ID,
                phone_number_id="phone-number-1",
                recipient_wa_id="573000000001",
                body="Hola desde Agents Factory",
                client_reference="outbound-1",
            )
        )

    assert result.outcome == "accepted"
    assert result.provider_message_id == "wamid.1"
    assert result.error_code is None
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == f"{GRAPH_API_BASE_URL}/phone-number-1/messages"
    assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN.decode()}"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "573000000001",
        "type": "text",
        "text": {"preview_url": False, "body": "Hola desde Agents Factory"},
    }
    assert ACCESS_TOKEN.decode() not in repr(provider)
    assert ACCESS_TOKEN.decode() not in repr(result)


@pytest.mark.asyncio
async def test_meta_provider_renders_only_validated_template_values() -> None:
    captured_payloads: list[dict[str, object]] = []

    def accept(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.template.1"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(accept)) as client:
        provider = MetaCloudApiProvider(
            app_secret=SecretStr("meta-app-secret"),
            access_tokens=StaticAccessTokenResolver(),
            http_client=client,
            graph_api_base_url=GRAPH_API_BASE_URL,
        )
        result = await provider.send_template(
            OutboundTemplateRequest(
                context=_context(),
                whatsapp_account_id=ACCOUNT_ID,
                phone_number_id="phone-number-1",
                recipient_wa_id="573000000001",
                template_name="appointment_confirmation",
                language="es_CO",
                body_parameters=("Daniel", "28 de agosto, 10:00"),
                client_reference="outbound-template-1",
            )
        )

    assert result.outcome == "accepted"
    assert result.provider_message_id == "wamid.template.1"
    assert captured_payloads == [
        {
            "messaging_product": "whatsapp",
            "to": "573000000001",
            "type": "template",
            "template": {
                "name": "appointment_confirmation",
                "language": {"code": "es_CO"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": "Daniel"},
                            {"type": "text", "text": "28 de agosto, 10:00"},
                        ],
                    }
                ],
            },
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_outcome", "expected_code"),
    [
        (
            httpx.Response(400, json={"error": {"code": 131047}}),
            "rejected",
            "meta_131047",
        ),
        (
            httpx.ReadTimeout("ambiguous provider timeout"),
            "uncertain",
            "provider_timeout",
        ),
    ],
)
async def test_meta_provider_classifies_rejection_and_ambiguous_timeout(
    response: httpx.Response | httpx.ReadTimeout,
    expected_outcome: str,
    expected_code: str,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = MetaCloudApiProvider(
            app_secret=SecretStr("meta-app-secret"),
            access_tokens=StaticAccessTokenResolver(),
            http_client=client,
            graph_api_base_url=GRAPH_API_BASE_URL,
        )
        result = await provider.send_text(
            OutboundTextRequest(
                context=_context(),
                whatsapp_account_id=ACCOUNT_ID,
                phone_number_id="phone-number-1",
                recipient_wa_id="573000000001",
                body="Hola",
                client_reference="outbound-1",
            )
        )

    assert result.outcome == expected_outcome
    assert result.error_code == expected_code
    assert result.provider_message_id is None
