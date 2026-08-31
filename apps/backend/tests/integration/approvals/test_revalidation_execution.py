import asyncio
from datetime import timedelta
from uuid import UUID
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from apps.backend.tests.approval_execution_support import approved, executor
from apps.backend.tests.approval_support import ApprovalHarness, EMAILS
from apps.backend.tests.appointments_support import NOW
from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401
from apps.backend.tests.integration.capabilities.test_appointments import world, BOOK  # noqa: F401
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.approvals.models import ApprovalRouteDraft
from agents_factory.modules.approvals.service import PersistedApprovalVerifier
from agents_factory.modules.capabilities.appointments.service import (
    AppointmentActionConnector,
)
from agents_factory.modules.integrations.contracts import ConnectorResult
from agents_factory.database import set_tenant_context


async def test_valid_duplicate_and_interrupted_execution(order_world, monkeypatch):  # noqa: F811
    w = order_world
    h, action, service, _ = await approved(w)
    results = await asyncio.wait_for(
        asyncio.gather(
            *(service.execute(context=w.context, action_id=action.id) for _ in range(2))
        ),
        timeout=20,
    )
    assert results[0] == results[1]
    assert results[0].reason_code == "request_recorded"
    fixture = next(iter(w.fixtures.values()))
    assert sum(req.method != "GET" for req in fixture.calls) == 1
    async with w.sessions.begin() as session:
        row = await ActionRepository(session, w.context).get(action.id)
        assert row.state == "SUCCEEDED" and row.execution_attempts == 1
        assert row.result["decision_result"] == results[0].model_dump(mode="json")
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='approvals.result'"
                )
            )
            == 1
        )
        events = (
            (
                await session.execute(
                    text(
                        "SELECT event_type FROM public.action_events WHERE action_id=:id ORDER BY version"
                    ),
                    {"id": action.id},
                )
            )
            .scalars()
            .all()
        )
        assert events == [
            "action.requested",
            "action.identity_verified",
            "action.awaiting_confirmation",
            "action.confirmed",
            "action.awaiting_approval",
            "action.approved",
            "action.executing",
            "action.succeeded",
        ]

    # New Action: simulate worker loss after the durable EXECUTING claim.
    fixture.order["meta_data"] = []
    new_action, request = await h.request()
    tokens = await h.notices(request)
    await h.service.decide(await h.verification(tokens[EMAILS[0]]))
    from agents_factory.modules.actions.service import ActionService

    with monkeypatch.context() as patch:
        patch.setattr(
            ActionService,
            "invoke_connector",
            AsyncMock(side_effect=asyncio.CancelledError),
        )
        with pytest.raises(asyncio.CancelledError):
            await service.execute(context=w.context, action_id=new_action.id)
    count = len(fixture.calls)
    recovered = await service.execute(context=w.context, action_id=new_action.id)
    assert recovered.reason_code == "outcome_unknown" and len(fixture.calls) == count


@pytest.mark.parametrize(
    "change,expected",
    [
        ("shipped", "order_already_shipped"),
        ("expired", "approval_expired"),
        ("spec", "precondition_changed"),
        ("route", "precondition_changed"),
        ("outage", "connector_unavailable"),
        ("ambiguous", "outcome_unknown"),
    ],
)
async def test_delayed_execution_guards(order_world, monkeypatch, change, expected):  # noqa: F811
    w = order_world
    h, action, service, specs = await approved(w)
    fixture = next(iter(w.fixtures.values()))
    if change == "shipped":
        fixture.order["status"] = "shipped"
    elif change == "expired":
        h.clock += timedelta(days=2)
    elif change == "spec":
        specs.active = False
    elif change == "route":
        await h.service.save_route(
            context=w.context,
            configuration=h.configuration.model_copy(update={"enabled": False}),
            expected_revision=h.route.revision,
        )
    elif change == "outage":
        monkeypatch.setattr(
            w.orders,
            "_provider",
            AsyncMock(
                return_value=ConnectorResult(
                    operation="orders.get_status",
                    status="FAILED",
                    error_code="provider_unavailable",
                )
            ),
        )
    elif change == "ambiguous":
        fixture.fail_write = True
    result = await service.execute(context=w.context, action_id=action.id)
    assert result.reason_code == expected and result.status != "succeeded"
    count = len(fixture.calls)
    assert await service.execute(context=w.context, action_id=action.id) == result
    assert len(fixture.calls) == count
    assert sum(req.method != "GET" for req in fixture.calls) == (
        1 if change == "ambiguous" else 0
    )


async def test_already_cancelled_appointment(world):  # noqa: F811
    w = world
    booking = await w.request("create_appointment", BOOK, level=1)
    await w.confirm(booking)
    booked = await w.execute(booking)
    appointment = UUID(booked.result["data"]["id"])
    h = await ApprovalHarness.create(w)
    h.clock = NOW
    await h.service.save_route(
        context=w.context,
        configuration=ApprovalRouteDraft(
            ref="appointment-approvals",
            capability="appointments",
            action="appointments.request_cancellation",
            authorized_emails=EMAILS,
        ),
    )
    action = await w.request(
        "request_cancellation",
        {"appointment_id": str(appointment), "reason": "Customer request"},
    )
    await w.confirm(action)
    request = await h.service.request(context=w.context, action_id=action.id)
    tokens = await h.notices(request)
    await h.service.decide(await h.verification(tokens[EMAILS[0]]))
    next(iter(w.calendar.events.values()))["status"] = "cancelled"
    count = w.calendar.writes
    service, _ = executor(
        w, h, lambda context, record: AppointmentActionConnector(w.appointments)
    )
    assert (
        await service.execute(context=w.context, action_id=action.id)
    ).reason_code == "appointment_already_cancelled"
    assert w.calendar.writes == count


async def test_action_service_rechecks_approval_reference(order_world):  # noqa: F811
    w = order_world
    h, action, _, _ = await approved(w)
    async with w.sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        await set_tenant_context(session, w.context.tenant_id)
        request = await h.service.get(
            context=w.context,
            request_id=(
                await session.scalar(
                    text("SELECT id FROM public.approval_requests WHERE action_id=:id"),
                    {"id": action.id},
                )
            ),
        )
        decision = await session.scalar(
            text("SELECT id FROM public.approval_decisions WHERE request_id=:id"),
            {"id": request.id},
        )
        actions = w.actions(session)
        actions._approval_verifier = PersistedApprovalVerifier(
            w.sessions, w.context, now=lambda: h.clock
        )
        await actions.approve_reference(
            action_id=action.id,
            parameter_digest=action.parameter_digest,
            approval_reference=str(decision),
        )
    h.clock += timedelta(days=2)
    async with w.sessions.begin() as session:
        actions = w.actions(session)
        actions._approval_verifier = PersistedApprovalVerifier(
            w.sessions, w.context, now=lambda: h.clock
        )
        outcome = await actions.execute(action_id=action.id)
        assert (
            outcome.state == "REJECTED"
            and outcome.result["reason_code"] == "approval_no_longer_valid"
        )
    assert not any(req.method != "GET" for req in next(iter(w.fixtures.values())).calls)


@pytest.mark.parametrize("failure", ["missing_connector", "invalid_receipt", "orphan"])
async def test_execution_fails_closed_without_reusable_connector(
    order_world,  # noqa: F811
    monkeypatch,
    failure,
):
    from agents_factory.modules.actions.service import ActionService

    w = order_world
    _, action, service, _ = await approved(w)

    def unavailable(*args):
        raise RuntimeError("fixture-configuration-unavailable")

    if failure == "missing_connector":
        service.connectors = unavailable
    elif failure == "invalid_receipt":
        monkeypatch.setattr(
            ActionService,
            "invoke_connector",
            AsyncMock(
                return_value=ConnectorResult(
                    operation=action.action_type, status="SUCCEEDED", data={}
                )
            ),
        )
    else:
        with monkeypatch.context() as patch:
            patch.setattr(
                ActionService,
                "invoke_connector",
                AsyncMock(side_effect=asyncio.CancelledError),
            )
            with pytest.raises(asyncio.CancelledError):
                await service.execute(context=w.context, action_id=action.id)
        service.agent_specs = unavailable
        service.connectors = unavailable
    result = await service.execute(context=w.context, action_id=action.id)
    assert result.reason_code == (
        "connector_unavailable" if failure == "missing_connector" else "outcome_unknown"
    )
    async with w.sessions.begin() as session:
        row = await ActionRepository(session, w.context).get(action.id)
        assert row.state == (
            "FAILED" if failure == "missing_connector" else "UNCERTAIN"
        )
    assert not any(req.method != "GET" for req in next(iter(w.fixtures.values())).calls)
