from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agents_factory.common.security import PlatformAdminAuthorizer
from agents_factory.database import set_tenant_context
from agents_factory.main import create_app
from agents_factory.modules.approvals.models import ApprovalError
from agents_factory.modules.approvals.service import PersistedApprovalVerifier
from apps.backend.tests.approval_support import EMAILS, ApprovalHarness
from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401


@pytest.fixture
async def session_factory(conversation_session_factory, clean_conversation_tables):
    async with conversation_session_factory.begin() as session:
        await session.execute(
            text(
                "GRANT agents_factory_admin TO CURRENT_USER WITH INHERIT FALSE, SET TRUE"
            )
        )
    return conversation_session_factory


async def test_approval_http_secrets_tenant_and_immutable_decision(order_world, caplog):  # noqa: F811
    world = order_world
    h = await ApprovalHarness.create(world)
    action, approval = await h.request()
    tokens = await h.notices(approval)
    link_value = tokens[EMAILS[0]]
    command = await h.verification(link_value)
    for context in (
        replace(world.context, actor_id=None),
        replace(world.context, actor_type="customer"),
    ):
        with pytest.raises(ApprovalError):
            await h.service.request(context=context, action_id=action.id)
    foreign = replace(world.context, tenant_id=uuid4())
    assert await h.service.get(context=foreign, request_id=approval.id) is None
    app = create_app(approval_service=h.service)
    app.state.database = SimpleNamespace(session_factory=world.sessions)
    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(AsyncMock())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=h.service.public_origin
    ) as client:
        admin = await client.post(
            f"/admin/tenants/{world.context.tenant_id}/approvals/actions/{action.id}"
        )
        assert admin.status_code == 401
        denied = await client.post(
            "/approvals/inspect", json={"link_token": link_value}
        )
        assert denied.status_code == 403
        headers = {"origin": h.service.public_origin}
        invalid = await client.post(
            "/approvals/decide",
            headers=headers,
            json={
                **command.model_dump(mode="json"),
                "link_token": link_value,
                "code": command.code.get_secret_value(),
                "challenge_id": "invalid",
            },
        )
        assert (
            invalid.status_code == 422
            and link_value not in invalid.text
            and command.code.get_secret_value() not in invalid.text
        )
        bad_token = await client.post(
            "/approvals/inspect", headers=headers, json={"link_token": link_value + "x"}
        )
        assert bad_token.status_code == 409
        inspected = await client.post(
            "/approvals/inspect", headers=headers, json={"link_token": link_value}
        )
        assert inspected.json() == {"status": "OPEN"}
        accepted = await client.post(
            "/approvals/decide",
            headers=headers,
            json={
                **command.model_dump(mode="json"),
                "link_token": link_value,
                "code": command.code.get_secret_value(),
            },
        )
        assert accepted.json() == {"status": "RECORDED"}
        closed = await client.post(
            "/approvals/inspect",
            headers=headers,
            json={"link_token": tokens[EMAILS[1]]},
        )
        assert closed.json() == {"status": "CLOSED"}
        for response in (
            admin,
            denied,
            invalid,
            bad_token,
            inspected,
            accepted,
            closed,
        ):
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["Referrer-Policy"] == "no-referrer"
    async with h.service.transaction(world.context) as repo:
        decision = await repo.decision(approval.id)
        assert decision.metadata == {} and decision.verification == "LINK_AND_EMAIL_OTP"
        audits = (
            (
                await repo.session.execute(
                    text("SELECT payload FROM public.audit_events")
                )
            )
            .scalars()
            .all()
        )
    assert link_value not in str(audits) + caplog.text
    assert command.code.get_secret_value() not in str(audits) + caplog.text
    verifier = PersistedApprovalVerifier(world.sessions, foreign)
    assert not await verifier.verify(
        route_ref=h.configuration.ref,
        approval_reference=str(decision.id),
        action_id=action.id,
        parameter_digest=action.parameter_digest,
    )
    async with world.sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, foreign.tenant_id)
        for table in (
            "approval_routes",
            "approval_requests",
            "approval_links",
            "approval_decisions",
        ):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )
    with pytest.raises(DBAPIError) as immutable:
        async with world.sessions.begin() as session:
            await session.execute(
                text(
                    "UPDATE public.approval_decisions SET decision='REJECT' WHERE id=:id"
                ),
                {"id": decision.id},
            )
    assert immutable.value.orig.sqlstate == "55000"
    with pytest.raises(DBAPIError) as reassigned:
        async with world.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(session, world.context.tenant_id)
            await session.execute(
                text(
                    "UPDATE public.approval_requests SET tenant_id=:tenant WHERE id=:id"
                ),
                {"tenant": foreign.tenant_id, "id": approval.id},
            )
    assert reassigned.value.orig.sqlstate == "42501"
