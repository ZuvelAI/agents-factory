from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from agents_factory.common.errors import DomainError
from agents_factory.common.security import JwksTokenVerifier
from agents_factory.config import ReviewBinding
from agents_factory.modules.whatsapp import review_router as review
from agents_factory.modules.whatsapp.router import TestMessageRequest as MessageRequest


def binding():
    return ReviewBinding(
        UUID("c5cd8d04-01f2-49be-aa27-1075520a2a20"),
        UUID("d4dfa61a-7ed6-4a87-877a-1d34e7dbf837"),
        "1894805611498111",
        "1334721596385520",
        "573103538756",
    )


def request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(settings=SimpleNamespace(review_binding=binding()))
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
async def test_auth_uses_server_binding_and_denies_unconfigured_review(
    monkeypatch, configured
):
    current = user()
    current["app_metadata"]["review_access"].update(
        {
            "tenant_id": "11111111-1111-4111-8111-111111111111",
            "account_id": "22222222-2222-4222-8222-222222222222",
        }
        if configured
        else {}
    )
    binding = (
        SimpleNamespace(
            tenant_id="11111111-1111-4111-8111-111111111111",
            account_id="22222222-2222-4222-8222-222222222222",
            waba_id="111111111111111",
            phone_number_id="222222222222222",
            recipient="15550123456",
        )
        if configured
        else None
    )
    settings = SimpleNamespace(
        supabase_url="https://auth.invalid",
        supabase_publishable_key=SecretStr("test-key"),
        review_binding=binding,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        state=SimpleNamespace(),
    )
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        review.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=current)
            ),
            **kwargs,
        ),
    )
    if configured:
        assert (
            str(await review.reviewer(request, "Bearer test-session")) == current["id"]
        )
    else:
        with pytest.raises(DomainError) as caught:
            await review.reviewer(request, "Bearer test-session")
        assert caught.value.status == 403


def user():
    return {
        "id": str(uuid4()),
        "is_anonymous": False,
        "app_metadata": {
            "platform_role": "meta_reviewer",
            "review_access": {
                "tenant_id": str(binding().tenant_id),
                "account_id": str(binding().account_id),
                "expires_at": (datetime.now(UTC) + timedelta(days=366)).isoformat(),
            },
        },
    }


def test_valid_review_access_is_not_admin_access():
    current = user()
    assert str(review.validate_review_user(current, binding())) == current["id"]
    claims = {
        **current,
        "sub": current["id"],
        "role": "authenticated",
        "session_id": str(uuid4()),
    }
    with pytest.raises(DomainError):
        JwksTokenVerifier._principal_from_claims(claims)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", str(uuid4())),
        ("account_id", str(uuid4())),
        ("expires_at", "2020-01-01T00:00:00+00:00"),
        ("expires_at", "invalid"),
        ("expires_at", "2099-01-01T00:00:00"),
    ],
)
def test_scope_and_expiry_fail_closed(field, value):
    current = user()
    current["app_metadata"]["review_access"][field] = value
    with pytest.raises(DomainError):
        review.validate_review_user(current, binding())


def test_user_editable_metadata_cannot_grant_review():
    current = user()
    current["user_metadata"] = current.pop("app_metadata")
    with pytest.raises(DomainError):
        review.validate_review_user(current, binding())


@pytest.mark.asyncio
async def test_other_recipient_never_queues(monkeypatch):
    monkeypatch.setattr(review, "verify_test_account", AsyncMock())
    queue = AsyncMock()
    monkeypatch.setattr(review, "queue_test_message", queue)
    with pytest.raises(DomainError):
        await review.send(
            MessageRequest(
                recipient="573001234567",
                template_name="hello_world",
                language="en_US",
                idempotency_key=uuid4(),
            ),
            request(),
            uuid4(),
            AsyncMock(),
        )
    queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_limit_never_queues(monkeypatch):
    monkeypatch.setattr(review, "verify_test_account", AsyncMock())
    queue = AsyncMock()
    monkeypatch.setattr(review, "queue_test_message", queue)
    session = AsyncMock()
    session.scalar.return_value = 10
    with pytest.raises(DomainError) as caught:
        await review.send(
            MessageRequest(
                recipient="573103538756",
                template_name="hello_world",
                language="en_US",
                idempotency_key=uuid4(),
            ),
            request(),
            uuid4(),
            session,
        )
    assert caught.value.status == 429
    queue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {},
        {"waba_id": "999"},
        {"phone_number_id": "999"},
        {"status": "inactive"},
        {"connection_mode": "COEXISTENCE"},
    ],
)
async def test_account_binding_revalidates_provider_assets_and_api_only_mode(change):
    row = {
        "waba_id": "1894805611498111",
        "phone_number_id": "1334721596385520",
        "status": "active",
        "connection_mode": "API_ONLY",
        **change,
    }
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = row
    session = AsyncMock()
    session.execute.side_effect = [None, result]
    if change:
        with pytest.raises(DomainError) as caught:
            await review.verify_test_account(session, binding())
        assert caught.value.status == 403
    else:
        await review.verify_test_account(session, binding())
    assert session.execute.call_args.args[1] == {
        "tenant": binding().tenant_id,
        "account": binding().account_id,
    }
