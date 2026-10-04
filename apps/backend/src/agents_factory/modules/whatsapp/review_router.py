"""Server-bound test-account review surface. Never grants platform-admin access."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.security import (
    AdminPrincipal,
    _authentication_error,
    _parse_bearer_token,
)
from agents_factory.common.errors import DomainError
from agents_factory.config import ReviewBinding, Settings
from agents_factory.dependencies import TransactionSession
from agents_factory.modules.whatsapp.router import (
    TestMessageRequest,
    load_test_templates,
    queue_test_message,
)

router = APIRouter(prefix="/review/whatsapp", tags=["restricted-review"])


def denied() -> DomainError:
    return DomainError(
        type="https://agents-factory.dev/problems/review-denied",
        title="Review access denied",
        status=403,
        detail="This review account cannot perform that operation.",
        code="review_denied",
    )


def require_review_binding(settings: Settings) -> ReviewBinding:
    binding = settings.review_binding
    if binding is None:
        raise denied()
    return binding


def validate_review_user(user: object, binding: ReviewBinding | None = None) -> UUID:
    """Only server-controlled, currently fetched metadata can authorize review."""
    if binding is None or not isinstance(user, dict):
        raise denied()
    try:
        metadata = user["app_metadata"]
        scope = metadata["review_access"]
        expiry = datetime.fromisoformat(scope["expires_at"])
        valid = (
            user.get("is_anonymous") is False
            and metadata.get("platform_role") == "meta_reviewer"
            and scope["tenant_id"] == str(binding.tenant_id)
            and scope["account_id"] == str(binding.account_id)
            and expiry.tzinfo is not None
            and expiry > datetime.now(UTC)
        )
        user_id = UUID(user["id"])
    except (AttributeError, KeyError, TypeError, ValueError):
        raise denied() from None
    if not valid:
        raise denied()
    return user_id


async def reviewer(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> UUID:
    review_bearer = _parse_bearer_token(authorization)
    settings = request.app.state.settings
    # Auth server verifies the token AND returns current metadata (revocation is immediate).
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {review_bearer}",
                    "apikey": settings.supabase_publishable_key.get_secret_value(),
                },
            )
            response.raise_for_status()
            user = response.json()
    except (httpx.HTTPError, ValueError):
        raise _authentication_error() from None
    user_id = validate_review_user(user, require_review_binding(settings))
    request.state.restricted_reviewer = True
    return user_id


Reviewer = Annotated[UUID, Depends(reviewer)]


async def verify_test_account(session: AsyncSession, binding: ReviewBinding) -> None:
    # Fixed IDs alone are insufficient if an operator later reconnects this record.
    from agents_factory.database import set_tenant_context

    await set_tenant_context(session, binding.tenant_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT waba_id, phone_number_id, status, connection_mode FROM public.whatsapp_accounts "
                    "WHERE tenant_id=:tenant AND id=:account"
                ),
                {"tenant": binding.tenant_id, "account": binding.account_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        row is None
        or row["waba_id"] != binding.waba_id
        or row["phone_number_id"] != binding.phone_number_id
        or row["status"] != "active"
        or row["connection_mode"] != "API_ONLY"
    ):
        raise denied()


@router.post("/templates")
async def templates(
    request: Request, user: Reviewer, session: TransactionSession
) -> list[dict[str, str]]:
    binding = require_review_binding(request.app.state.settings)
    await verify_test_account(session, binding)
    # Existing business operation is reused; no admin JWT, membership, or DB role is granted.
    return await load_test_templates(
        binding.tenant_id,
        binding.account_id,
        request,
        AdminPrincipal(user, UUID(int=0)),
        session,
    )


@router.post("/messages", status_code=202)
async def send(
    payload: TestMessageRequest,
    request: Request,
    user: Reviewer,
    session: TransactionSession,
) -> dict[str, str]:
    binding = require_review_binding(request.app.state.settings)
    await verify_test_account(session, binding)
    # This recipient was authorized by the owner for the Meta test account.
    if payload.recipient != binding.recipient:
        raise denied()
    # Serialize review submissions across processes, and cap real outbound messages.
    await session.execute(text("SELECT pg_advisory_xact_lock(193781, 451318)"))
    count = await session.scalar(
        text(
            "SELECT count(*) FROM public.outbound_messages WHERE tenant_id=:tenant "
            "AND whatsapp_account_id=:account AND created_at > now() - interval '24 hours'"
        ),
        {"tenant": binding.tenant_id, "account": binding.account_id},
    )
    if count >= 10:
        raise DomainError(
            type="https://agents-factory.dev/problems/review-limit",
            title="Review limit",
            status=429,
            detail="Test message daily limit reached.",
            code="review_limit",
        )
    return await queue_test_message(
        binding.tenant_id,
        binding.account_id,
        payload,
        request,
        AdminPrincipal(user, UUID(int=0)),
    )
