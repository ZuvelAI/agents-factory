import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from agents_factory.common.queue import JobEnvelope
from agents_factory.modules.capabilities.returns_claims.models import (
    PreparedClaimIntake,
)
from agents_factory.modules.cases.adapters import (
    PersistentClaimCases,
    PersistentOrderCases,
)
from agents_factory.modules.cases.claims_contracts import ClaimCaseConflict
from agents_factory.modules.cases.delivery import PersistentClaimDeliveryLedger
from agents_factory.modules.cases.models import CasePolicy, CaseTransition
from agents_factory.modules.cases.service import CaseService
from agents_factory.modules.integrations.contracts import ConnectorResult
from scheduler.case_jobs import configure_case_jobs
from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401
from apps.backend.tests.integration.capabilities.test_returns_claims import claims_world  # noqa: F401


def attach_persistence(world, *, now=None, policy=None):
    service = CaseService(
        world.base.sessions,
        now=now,
        policies={world.base.context.tenant_id: policy} if policy else None,
    )
    world.workflow.cases = PersistentClaimCases(service)
    world.workflow.destination = replace(
        world.workflow.destination,
        ledger=PersistentClaimDeliveryLedger(world.base.sessions),
    )
    return service


async def submit(world, **extras):
    action = await world.request(
        {
            "issue_type": "damaged_product",
            "order_id": "42",
            "description": "Producto dañado",
            "item_ids": ["1"],
            **extras,
        }
    )
    await world.confirm(action)
    result = await world.execute(action)
    assert result.state == "SUCCEEDED", result.result
    return UUID(result.result["data"]["case_id"]), action


async def test_real_claim_persistence_concurrency_and_outer_action_rollback(
    claims_world,  # noqa: F811
):
    world = claims_world
    service = attach_persistence(world)
    context = world.base.context
    action = await world.request(
        {
            "issue_type": "damaged_product",
            "order_id": "42",
            "description": "Producto dañado",
            "item_ids": ["1"],
            "evidence_ids": [str(world.evidence_id)],
        }
    )
    await world.confirm(action)
    with pytest.raises(RuntimeError, match="outer transaction"):
        await world.execute(action, rollback=True)
    writes = list(world.google.writes)
    assert writes
    # New adapter instances use only PostgreSQL, not an in-process replay cache.
    attach_persistence(world)
    result = await world.execute(action)
    assert result.state == "SUCCEEDED"
    assert world.google.writes == writes
    case_id = UUID(result.result["data"]["case_id"])
    case = await service.get(context=context, customer_ref="customer", case_id=case_id)
    assert case.revision == 1
    prepared = PreparedClaimIntake.model_validate(action.parameters["_intake"])
    receipts = await asyncio.gather(
        *(
            PersistentClaimCases(CaseService(world.base.sessions)).upsert(
                context=context,
                action_id=uuid4(),
                parameter_digest=action.parameter_digest,
                intake=prepared,
                expected_revision=0,
                case_id=None,
            )
            for _ in range(2)
        )
    )
    assert {item.case_id for item in receipts} == {case_id}
    assert {item.revision for item in receipts} == {1}
    correction = await world.request(
        {"case_id": str(case_id), "description": "La carcasa llegó rota"}
    )
    await world.confirm(correction)
    assert (await world.execute(correction)).state == "SUCCEEDED"
    current = await service.get(
        context=context, customer_ref="customer", case_id=case_id
    )
    assert current.revision == 2
    with pytest.raises(ClaimCaseConflict):
        await PersistentClaimCases(service).upsert(
            context=context,
            action_id=uuid4(),
            parameter_digest=action.parameter_digest,
            intake=prepared,
            expected_revision=1,
            case_id=case_id,
        )
    with pytest.raises(ClaimCaseConflict):
        await PersistentClaimCases(service).upsert(
            context=context,
            action_id=action.id,
            parameter_digest="0" * 64,
            intake=prepared,
            expected_revision=0,
            case_id=None,
        )
    history = await service.history(
        context=context, customer_ref="customer", case_id=case_id
    )
    assert sum(event.event_type == "CREATED" for event in history) == 1
    assert world.evidence_id in history[0].evidence_ids
    assert history[0].action_reference == action.id
    async with world.base.sessions.begin() as session:
        assert await session.scalar(text("SELECT count(*) FROM public.cases")) == 1
        results = (
            (
                await session.execute(
                    text(
                        "SELECT result FROM public.case_delivery_operations WHERE operation='drive.store_evidence'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert results and results[0]["data"]["file_id"]


async def test_case_lifecycle_reopen_silence_window_targets_and_scheduler(claims_world):  # noqa: F811
    from types import SimpleNamespace

    world = claims_world
    clock = [datetime.now(UTC)]
    policy = CasePolicy(
        priority_by_issue={"damaged_product": "HIGH"}, close_after_hours=2
    )
    service = attach_persistence(world, now=lambda: clock[0], policy=policy)
    context = world.base.context
    case_id, _ = await submit(world)
    case = await service.get(context=context, customer_ref="customer", case_id=case_id)
    assert case.priority == "HIGH" and case.target_at - clock[0] == timedelta(hours=4)
    clock[0] = case.approaching_at
    await service.process_timer(context=context, case_id=case_id)
    await service.process_timer(context=context, case_id=case_id)
    clock[0] = case.target_at
    await service.process_timer(context=context, case_id=case_id)
    history = await service.history(
        context=context, customer_ref="customer", case_id=case_id
    )
    assert [
        event.reason for event in history if event.event_type == "RESPONSE_TARGET_ALERT"
    ] == ["APPROACHING_TARGET", "OVERDUE"]
    # Status reads don't create records, events, or WhatsApp reminders.
    safe = await service.status(
        context=context, customer_ref="customer", case_id=case_id
    )
    assert set(safe.model_dump()) == {"case_id", "status", "customer_result"}
    assert (
        await service.history(context=context, customer_ref="customer", case_id=case_id)
        == history
    )
    assert (
        await service.status(context=context, customer_ref="other", case_id=case_id)
        is None
    )
    assert (
        await service.status(
            context=replace(context, tenant_id=uuid4()),
            customer_ref="customer",
            case_id=case_id,
        )
        is None
    )

    async def move(target, **kwargs):
        nonlocal case
        case = await service.get(
            context=context, customer_ref="customer", case_id=case_id
        )
        command = CaseTransition(
            operation_id=uuid4(),
            expected_revision=case.revision,
            target=target,
            reason="Verified backoffice action",
            **kwargs,
        )
        case = await service.transition(
            context=context, customer_ref="customer", case_id=case_id, command=command
        )
        return command

    if case.status == "AWAITING_INFORMATION":
        await move("READY_FOR_REVIEW")
    await move("PENDING_APPROVAL")
    async with world.base.sessions.begin() as session:
        assert (
            await session.scalar(
                text("SELECT control_state FROM public.conversations WHERE id=:id"),
                {"id": world.base.conversation},
            )
            == "AI_ACTIVE"
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic LIKE 'outbound.%' OR topic='whatsapp.outbound.send'"
                )
            )
            == 0
        )
    with pytest.raises(ClaimCaseConflict, match="approval_reference"):
        await move("IN_PROGRESS")
    await move(
        "IN_PROGRESS",
        approval_reference="backoffice-reference-only-not-action-authorization",
    )
    resolution = await move(
        "RESOLVED", customer_result="El equipo registró la solución del incidente."
    )
    assert case.close_at == clock[0] + timedelta(hours=2)
    assert case.result_recorded_by == context.actor_id
    assert (
        await service.transition(
            context=context,
            customer_ref="customer",
            case_id=case_id,
            command=resolution,
        )
        == case
    )
    clock[0] += timedelta(hours=1)
    old_close = case.close_at
    case = await service.record_customer_response(
        context=context,
        customer_ref="customer",
        case_id=case_id,
        operation_id=uuid4(),
        issue_persists=False,
        reason="Customer acknowledged",
    )
    clock[0] = old_close
    await service.process_timer(context=context, case_id=case_id)
    assert (
        await service.get(context=context, customer_ref="customer", case_id=case_id)
    ).status == "RESOLVED"
    case = await service.record_customer_response(
        context=context,
        customer_ref="customer",
        case_id=case_id,
        operation_id=uuid4(),
        issue_persists=True,
        reason="Customer reports the issue persists",
    )
    assert (
        case.id == case_id
        and case.status == "REOPENED"
        and case.customer_result is None
    )
    await move("IN_PROGRESS")
    await move("RESOLVED")
    clock[0] = case.close_at
    await service.process_timer(context=context, case_id=case_id)
    assert (
        await service.get(context=context, customer_ref="customer", case_id=case_id)
    ).status == "CLOSED"
    successor = await service.report_persisting_issue(
        context=context,
        customer_ref="customer",
        case_id=case_id,
        operation_id=uuid4(),
        reason="Customer reports issue outside reopen window",
    )
    assert successor.id != case_id and successor.status == "OPEN"
    another = await service.report_persisting_issue(
        context=context,
        customer_ref="customer",
        case_id=case_id,
        operation_id=uuid4(),
        reason="Second report reuses active successor",
    )
    assert another.id == successor.id
    # Scheduler registration and envelope-to-case dispatch use the durable DB state.
    worker = {"job_handlers": {}}
    await configure_case_jobs(
        worker, database=SimpleNamespace(session_factory=world.base.sessions)
    )
    async with world.base.sessions.begin() as session:
        timer = (
            (
                await session.execute(
                    text(
                        "SELECT id,payload FROM public.outbox_jobs WHERE topic='cases.timer' LIMIT 1"
                    )
                )
            )
            .mappings()
            .one()
        )
    envelope = JobEnvelope(
        job_id=timer["id"],
        tenant_id=context.tenant_id,
        kind="cases.timer",
        aggregate_id=UUID(timer["payload"]["aggregate_id"]),
    )
    await worker["job_handlers"]["cases.timer"](envelope)


async def test_delivery_claim_survives_interruption_and_never_resends(order_world):  # noqa: F811
    world, calls = order_world, []
    first = PersistentClaimDeliveryLedger(world.sessions)
    second = PersistentClaimDeliveryLedger(world.sessions)
    context = world.context

    async def effect():
        calls.append("write")
        return ConnectorResult(
            operation="sheets.update_row", status="SUCCEEDED", data={"row": 2}
        )

    results = await asyncio.gather(
        *(
            ledger.once(
                context=context,
                key="claims:concurrent",
                digest="1" * 64,
                operation="sheets.update_row",
                effect=effect,
            )
            for ledger in (first, second)
        )
    )
    assert len(calls) == 1 and all(result.status == "SUCCEEDED" for result in results)
    mismatch = await second.once(
        context=context,
        key="claims:concurrent",
        digest="2" * 64,
        operation="sheets.update_row",
        effect=effect,
    )
    assert mismatch.status == "REJECTED" and len(calls) == 1

    async def crash():
        calls.append("unknown-provider-outcome")
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await first.once(
            context=context,
            key="claims:interrupted",
            digest="3" * 64,
            operation="sheets.update_row",
            effect=crash,
        )
    uncertain = await second.once(
        context=context,
        key="claims:interrupted",
        digest="3" * 64,
        operation="sheets.update_row",
        effect=effect,
    )
    assert uncertain.status == "UNCERTAIN" and len(calls) == 2
    assert (
        await first.once(
            context=context,
            key="claims:interrupted",
            digest="3" * 64,
            operation="sheets.update_row",
            effect=effect,
        )
        == uncertain
    )
    assert len(calls) == 2
    # The legacy Orders capability now uses the same durable Cases service.
    world.orders.cases = PersistentOrderCases(CaseService(world.sessions))
    binding = next(iter(world.bindings))
    request = await world.request(
        binding,
        "orders.create_claim",
        {
            "issue_type": "delivery_delay",
            "order_id": "42",
            "description": "Aún no llegó el pedido",
        },
    )
    await world.confirm(request)
    result = await world.execute(request)
    assert result.state == "SUCCEEDED"
    case_id = UUID(result.result["data"]["case_id"])
    repeat = await world.request(
        binding,
        "orders.create_claim",
        {
            "issue_type": "delivery_delay",
            "order_id": "42",
            "description": "Aún no llegó el pedido",
        },
    )
    await world.confirm(repeat)
    result = await world.execute(repeat)
    assert (
        UUID(result.result["data"]["case_id"]) == case_id
        and result.result["data"]["reused"]
    )
