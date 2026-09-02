from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import text

from apps.backend.tests.approval_execution_support import approved
from apps.backend.tests.approval_support import EMAILS
from apps.backend.tests.handoff_support import HandoffHarness
from apps.backend.tests.integration.capabilities.test_orders import order_world  # noqa: F401
from agent_worker.approval_jobs import configure_approval_execution
from agents_factory.common.queue import JobEnvelope, OutboxDispatcher
from agents_factory.modules.whatsapp.contracts import (
    ProviderMessageResult,
    WhatsAppDeliveryStatusEvent,
)
from agents_factory.modules.whatsapp.outbound_service import (
    OutboundMessageService,
    OutboundStatusReconciler,
)
from agents_factory.modules.whatsapp.template_service import (
    TemplateService,
    SyncedWhatsAppTemplate,
)


async def test_result_delivery_and_human_hold(order_world):  # noqa: F811
    w = order_world
    h, action, service, _ = await approved(w)
    handoff = await HandoffHarness.create(w.sessions, w.context, w.conversation)
    handoff_record = await handoff.request()
    await handoff.human_event(handoff_record)
    async with w.sessions.begin() as session:
        job_id = await session.scalar(
            text("SELECT id FROM public.outbox_jobs WHERE topic='approvals.execute'")
        )
        account = await session.scalar(
            text("SELECT whatsapp_account_id FROM public.conversations WHERE id=:id"),
            {"id": w.conversation},
        )
    await TemplateService(session_factory=w.sessions, context=w.context).sync(
        whatsapp_account_id=account,
        templates=[
            SyncedWhatsAppTemplate(
                "approval-result",
                "approval_result",
                "es",
                "APPROVED",
                "UTILITY",
                ("request_id", "result"),
            )
        ],
    )
    worker = {"approval_execution_service": service, "job_handlers": {}}
    configure_approval_execution(worker)
    await worker["job_handlers"]["approvals.execute"](
        JobEnvelope(job_id, w.context.tenant_id, "approvals.execute", action.id)
    )
    assert await service.notify(context=w.context, action_id=action.id) is None
    async with w.sessions.begin() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM public.outbound_messages"))
            == 0
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM public.messages WHERE sender_type='ai'")
            )
            == 0
        )
    # Held jobs do not consume delivery attempts while a human is in control.
    redis = AsyncMock()
    dispatcher = OutboxDispatcher(
        session_factory=w.sessions,
        queue=redis,
        queue_by_kind={"approvals.result.held": "agent"},
    )
    assert (await dispatcher.dispatch_once()).dispatched == 0
    async with w.sessions.begin() as session:
        assert await session.scalar(
            text(
                "SELECT available_at>now() AND attempt_count=0 FROM public.outbox_jobs WHERE topic='approvals.result.held'"
            )
        )
    await handoff.human_event(handoff_record, kind="END", sequence=1)
    async with w.sessions.begin() as session:
        # Advance the hold's eligibility without sleeping or rerunning other jobs.
        await session.execute(
            text(
                "UPDATE public.outbox_jobs SET available_at=now()-interval '1 minute' WHERE topic='approvals.result.held'"
            )
        )
    assert (await dispatcher.dispatch_once()).dispatched == 1
    outbound = await service.notify(context=w.context, action_id=action.id)
    assert await service.notify(context=w.context, action_id=action.id) == outbound
    provider = AsyncMock()
    provider.send_template.return_value = ProviderMessageResult(
        outcome="accepted", provider_message_id="wamid.approval33"
    )
    sender = OutboundMessageService(
        session_factory=w.sessions, context=w.context, provider=provider
    )
    assert (await sender.send(outbound)).status == "ACCEPTED"
    assert (await sender.send(outbound)).status == "ACCEPTED"
    assert provider.send_template.await_count == 1
    assert (
        "Esto no confirma una cancelación"
        in provider.send_template.call_args.args[0].body_parameters[1]
    )
    async with w.sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        assert await OutboundStatusReconciler(session).reconcile(
            context=w.context,
            whatsapp_account_id=account,
            event=WhatsAppDeliveryStatusEvent(
                waba_id="fixture",
                phone_number_id="fixture",
                whatsapp_message_id="wamid.approval33",
                recipient_wa_id="573000000026",
                status="delivered",
                occurred_at=h.clock,
                raw_payload={},
            ),
        )
        status = (
            (
                await session.execute(
                    text(
                        "SELECT status,status_history FROM public.outbound_messages WHERE id=:id"
                    ),
                    {"id": outbound},
                )
            )
            .mappings()
            .one()
        )
        assert status["status"] == "DELIVERED"
        assert len(status["status_history"]) >= 4
        payloads = (
            (
                await session.execute(
                    text("SELECT payload FROM public.audit_events WHERE entity_id=:id"),
                    {"id": action.id},
                )
            )
            .scalars()
            .all()
        )
        assert any(p.get("outbound_message_id") == str(outbound) for p in payloads)
        assert any("notification_job_id" in p for p in payloads)


async def test_rejection_notifies_without_execute_and_job_tenant_binding(order_world):  # noqa: F811
    w = order_world
    h, _, service, _ = await approved(w)
    action, request = await h.request()
    tokens = await h.notices(request)
    await h.service.decide(await h.verification(tokens[EMAILS[0]], decision="REJECT"))
    async with w.sessions.begin() as session:
        result = await session.scalar(
            text("SELECT result FROM public.actions WHERE id=:id"), {"id": action.id}
        )
        assert result["decision_result"]["reason_code"] == "reviewer_rejected"
        job = (
            (
                await session.execute(
                    text(
                        "SELECT id,payload FROM public.outbox_jobs WHERE topic='approvals.result' AND payload->>'aggregate_id'=:id"
                    ),
                    {"id": str(action.id)},
                )
            )
            .mappings()
            .one()
        )
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic='approvals.execute' AND payload->>'aggregate_id'=:id"
                ),
                {"id": str(action.id)},
            )
            == 0
        )
    worker = {"approval_execution_service": service, "job_handlers": {}}
    configure_approval_execution(worker)
    import pytest

    with pytest.raises(ValueError, match="binding_mismatch"):
        await worker["job_handlers"]["approvals.result"](
            JobEnvelope(job["id"], uuid4(), "approvals.result", action.id)
        )
