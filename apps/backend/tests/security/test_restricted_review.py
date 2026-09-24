from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agents_factory.common.errors import DomainError
from agents_factory.common.security import JwksTokenVerifier
from agents_factory.modules.whatsapp import review_router as review
from agents_factory.modules.whatsapp.router import TestMessageRequest as MessageRequest


def user():
    return {"id": str(uuid4()), "is_anonymous": False, "app_metadata": {
        "platform_role": "meta_reviewer", "review_access": {
            "tenant_id": str(review.TENANT), "account_id": str(review.ACCOUNT),
            "expires_at": (datetime.now(UTC) + timedelta(days=366)).isoformat(),
        },
    }}


def test_valid_review_access_is_not_admin_access():
    current = user()
    assert str(review.validate_review_user(current)) == current["id"]
    claims = {**current, "sub": current["id"], "role": "authenticated", "session_id": str(uuid4())}
    with pytest.raises(DomainError):
        JwksTokenVerifier._principal_from_claims(claims)


@pytest.mark.parametrize("field,value", [
    ("tenant_id", str(uuid4())), ("account_id", str(uuid4())),
    ("expires_at", "2020-01-01T00:00:00+00:00"), ("expires_at", "invalid"),
    ("expires_at", "2099-01-01T00:00:00"),
])
def test_scope_and_expiry_fail_closed(field, value):
    current = user()
    current["app_metadata"]["review_access"][field] = value
    with pytest.raises(DomainError):
        review.validate_review_user(current)


def test_user_editable_metadata_cannot_grant_review():
    current = user()
    current["user_metadata"] = current.pop("app_metadata")
    with pytest.raises(DomainError):
        review.validate_review_user(current)


@pytest.mark.asyncio
async def test_other_recipient_never_queues(monkeypatch):
    monkeypatch.setattr(review, "verify_test_account", AsyncMock())
    queue = AsyncMock()
    monkeypatch.setattr(review, "queue_test_message", queue)
    with pytest.raises(DomainError):
        await review.send(MessageRequest(recipient="573001234567", template_name="hello_world",
                                        language="en_US", idempotency_key=uuid4()),
                          SimpleNamespace(), uuid4(), AsyncMock())
    queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_limit_never_queues(monkeypatch):
    monkeypatch.setattr(review, "verify_test_account", AsyncMock())
    queue = AsyncMock()
    monkeypatch.setattr(review, "queue_test_message", queue)
    session = AsyncMock()
    session.scalar.return_value = 10
    with pytest.raises(DomainError) as caught:
        await review.send(MessageRequest(recipient="573103538756", template_name="hello_world",
                                        language="en_US", idempotency_key=uuid4()),
                          SimpleNamespace(), uuid4(), session)
    assert caught.value.status == 429
    queue.assert_not_awaited()
