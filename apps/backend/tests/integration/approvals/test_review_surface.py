from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from pydantic import SecretStr
from sqlalchemy import text

from agents_factory.main import create_app
from agents_factory.modules.approvals.models import VerifyInput
from agents_factory.modules.approvals.rate_limit import RedisApprovalRateLimiter
from apps.backend.tests.approval_support import EMAILS, ApprovalHarness
from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401


async def test_verified_review_result_and_public_rate_boundary(order_world, caplog):  # noqa: F811
    world = order_world
    h = await ApprovalHarness.create(world)
    _, approval = await h.request()
    links = await h.notices(approval)
    command = await h.verification(links[EMAILS[0]])
    proof = VerifyInput.model_validate(
        command.model_dump(exclude={"decision", "requested_result"})
    )
    wrong = proof.model_copy(update={"code": SecretStr("xxxxxx")})
    denied = await h.service.review(wrong)
    assert denied.status == "INVALID_VERIFICATION" and denied.details is None
    reviewed = await h.service.review(proof)
    assert reviewed.details.resource_reference == "42"
    assert reviewed.details.action == "orders.request_order_cancellation"
    assert reviewed.details.expires_at <= h.clock + timedelta(seconds=600)
    assert (
        "customer" not in reviewed.model_dump_json()
        and "parameter_digest" not in reviewed.model_dump_json()
    )
    async with h.service.transaction(world.context) as repo:
        assert await repo.decision(approval.id) is None
        assert (
            next(
                link
                for link in await repo.links(approval.id)
                if link.email == EMAILS[0]
            ).otp_attempts
            == 1
        )
    app = create_app(approval_service=h.service)
    counter = SimpleNamespace(allow=AsyncMock(return_value=True))
    app.state.approval_rate_limiter = counter
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url=h.service.public_origin,
        headers={"origin": h.service.public_origin},
    ) as client:
        payload = {
            **command.model_dump(mode="json"),
            "link_token": links[EMAILS[0]],
            "code": command.code.get_secret_value(),
        }
        review_payload = {
            key: val
            for key, val in payload.items()
            if key not in {"decision", "requested_result"}
        }
        checked = await client.post("/approvals/review", json=review_payload)
        assert checked.json()["details"]["request_id"] == str(approval.id)
        counter.allow.return_value = False
        limited = await client.post("/approvals/decision", json=payload)
        assert (
            limited.status_code == 429
            and limited.headers["cache-control"] == "no-store"
        )
        counter.allow.side_effect = RuntimeError("private redis diagnostics")
        unavailable = await client.post("/approvals/decision", json=payload)
        assert (
            unavailable.status_code >= 500 and "private redis" not in unavailable.text
        )
        counter.allow.side_effect = None
        counter.allow.return_value = True
        won = await client.post("/approvals/decision", json=payload)
        assert won.json()["result"]["status"] == "pending_execution"
        assert won.json()["result"]["next_actions"] == []
        assert (await client.post("/approvals/review", json=review_payload)).json() == {
            "status": "CLOSED",
            "details": None,
        }
        assert (await client.post("/approvals/decision", json=payload)).json() == {
            "status": "CLOSED",
            "result": None,
        }
        oversized = await client.post(
            "/approvals/review",
            content=b"x" * 17000,
            headers={"content-type": "application/json"},
        )
        assert oversized.status_code == 413
    assert (
        links[EMAILS[0]] not in caplog.text
        and command.code.get_secret_value() not in caplog.text
    )
    assert all(
        links[EMAILS[0]] not in str(call) and EMAILS[0] not in str(call)
        for call in counter.allow.call_args_list
    )
    # The Redis adapter delegates increment + expiry as one atomic script.
    redis = SimpleNamespace(eval=AsyncMock(side_effect=[1, 2, 3]))
    limiter = RedisApprovalRateLimiter(redis)
    assert await limiter.allow("opaque", limit=2, seconds=60)
    assert await limiter.allow("opaque", limit=2, seconds=60)
    assert not await limiter.allow("opaque", limit=2, seconds=60)
    assert (
        "EXPIRE" in redis.eval.call_args.args[0]
        and redis.eval.call_args.args[2] == "approvals:rate:opaque"
    )
    async with world.sessions.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.approval_decisions"))
            == 1
        )
