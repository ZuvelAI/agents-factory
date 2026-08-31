import asyncio
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
from agents_factory.modules.capabilities.returns_claims.models import (
    ClaimContribution,
    PreparedClaimIntake,
)
from agents_factory.modules.cases.adapters import PersistentClaimCases
from agents_factory.modules.cases.claims_contracts import ClaimCaseConflict
from agents_factory.modules.cases.models import CaseTransition
from agents_factory.modules.cases.service import CaseService
from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401
from apps.backend.tests.integration.capabilities.test_returns_claims import claims_world  # noqa: F401


@pytest.fixture
async def session_factory(conversation_session_factory, clean_conversation_tables):
    # This fixture exercises backend services as well as the app-role boundary.
    # The enclosing isolated security fixture restores both SET grants at teardown.
    async with conversation_session_factory.begin() as session:
        await session.execute(
            text(
                "GRANT agents_factory_admin TO CURRENT_USER WITH INHERIT FALSE, SET TRUE"
            )
        )
    return conversation_session_factory


async def test_case_actor_customer_rls_history_and_message_provenance(claims_world):  # noqa: F811
    world = claims_world
    context, sessions = world.base.context, world.base.sessions
    service = CaseService(sessions)
    adapter = PersistentClaimCases(service)
    action = await world.request(
        {"issue_type": "damaged_product", "order_id": "42", "description": "Daño"}
    )
    prepared = PreparedClaimIntake.model_validate(action.parameters["_intake"])
    messages = [uuid4(), uuid4()]
    # Distinct concurrent reports with the same facts must retain BOTH sources.
    receipts = await asyncio.gather(
        *(
            adapter.upsert(
                context=context,
                action_id=uuid4(),
                parameter_digest=action.parameter_digest,
                intake=prepared.model_copy(
                    update={
                        "contributions": (
                            ClaimContribution(
                                message_id=message, patch_digest="a" * 64
                            ),
                        )
                    }
                ),
                expected_revision=0,
                case_id=None,
            )
            for message in messages
        )
    )
    case_id = receipts[0].case_id
    case = await adapter.get(context=context, customer_ref="customer", case_id=case_id)
    assert {part.message_id for part in case.intake.contributions} == set(messages)
    assert case.revision == 1 and receipts[1].case_id == case_id
    assert (
        await adapter.get(context=context, customer_ref="other", case_id=case_id)
        is None
    )
    assert (
        await adapter.get(
            context=replace(context, tenant_id=uuid4()),
            customer_ref="customer",
            case_id=case_id,
        )
        is None
    )
    for invalid_context in (
        replace(context, actor_id=None),
        replace(context, actor_type="customer"),
    ):
        with pytest.raises(ClaimCaseConflict, match="backend_actor"):
            await adapter.upsert(
                context=invalid_context,
                action_id=uuid4(),
                parameter_digest=action.parameter_digest,
                intake=prepared,
                expected_revision=1,
                case_id=case_id,
            )
    with pytest.raises(ClaimCaseConflict, match="scope"):
        await adapter.upsert(
            context=replace(context, tenant_id=uuid4()),
            action_id=uuid4(),
            parameter_digest=action.parameter_digest,
            intake=prepared,
            expected_revision=0,
            case_id=None,
        )
    with pytest.raises(ClaimCaseConflict, match="message_replay"):
        await adapter.upsert(
            context=context,
            action_id=uuid4(),
            parameter_digest=action.parameter_digest,
            intake=prepared.model_copy(
                update={
                    "contributions": (
                        ClaimContribution(
                            message_id=messages[0], patch_digest="b" * 64
                        ),
                    )
                }
            ),
            expected_revision=1,
            case_id=case_id,
        )
    with pytest.raises(ClaimCaseConflict, match="backoffice"):
        await service.transition(
            context=replace(context, actor_type="system"),
            customer_ref="customer",
            case_id=case_id,
            command=CaseTransition(
                operation_id=uuid4(),
                expected_revision=1,
                target="READY_FOR_REVIEW",
                reason="Agent request",
            ),
        )
    changed = await service.transition(
        context=context,
        customer_ref="customer",
        case_id=case_id,
        command=CaseTransition(
            operation_id=uuid4(),
            expected_revision=1,
            target="READY_FOR_REVIEW",
            reason="Human review",
        ),
    )
    with pytest.raises(ClaimCaseConflict, match="backoffice"):
        await adapter.upsert(
            context=context,
            action_id=uuid4(),
            parameter_digest=action.parameter_digest,
            intake=prepared,
            expected_revision=1,
            case_id=case_id,
        )
    assert (
        await adapter.get(context=context, customer_ref="customer", case_id=case_id)
    ).revision == changed.revision
    # Defense in depth: even an unfiltered SELECT through the app role is scoped.
    async with sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, uuid4())
        assert await session.scalar(text("SELECT count(*) FROM public.cases")) == 0
    with pytest.raises(DBAPIError) as rewrite:
        async with sessions.begin() as session:
            await session.execute(
                text(
                    "UPDATE public.case_events SET reason='rewrite' WHERE case_id=:id"
                ),
                {"id": case_id},
            )
    assert rewrite.value.orig.sqlstate == "55000"
    with pytest.raises(DBAPIError) as reassign:
        async with sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(session, context.tenant_id)
            await session.execute(
                text("UPDATE public.cases SET tenant_id=:other WHERE id=:id"),
                {"id": case_id, "other": uuid4()},
            )
    assert reassign.value.orig.sqlstate == "42501"
    app = create_app()
    app.state.database = SimpleNamespace(session_factory=sessions)
    app.state.platform_admin_authorizer = PlatformAdminAuthorizer(AsyncMock())
    app.state.case_service = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/admin/tenants/{context.tenant_id}/cases/{case_id}",
            params={"customer_ref": "customer"},
        )
        assert response.status_code == 401
