from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.backend.tests.appointments_support import (
    ACCOUNT,
    CONNECTION,
    NOW,
    FakeCalendar,
    configuration,
)
from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.outbox import OutboxService
from agents_factory.common.queue import JobEnvelope
from agents_factory.database import set_tenant_context
from agents_factory.modules.actions.models import ActionRecord, ActionOutcome
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.capabilities.appointments.communications import (
    prepare_appointment_notification,
)
from agents_factory.modules.capabilities.appointments.repository import (
    AppointmentUnavailable,
)
from agents_factory.modules.capabilities.appointments.service import (
    AppointmentsService,
    AppointmentActionConnector,
)
from agents_factory.modules.identity.models import IdentityAssessment, IdentityLevel
from agents_factory.modules.identity.service import IdentityService
from agents_factory.modules.whatsapp.template_service import (
    SyncedWhatsAppTemplate,
    TemplateService,
)


class Approval:
    async def verify(
        self,
        *,
        route_ref: str,
        approval_reference: str,
        action_id: UUID,
        parameter_digest: str,
    ) -> bool:
        return (
            route_ref == "appointment-approvals"
            and approval_reference == "verified-approval"
            and bool(action_id and parameter_digest)
        )


@dataclass
class World:
    sessions: async_sessionmaker[AsyncSession]
    context: TenantContext
    conversation: UUID
    calendar: FakeCalendar
    appointments: AppointmentsService

    def actions(self, session: AsyncSession) -> ActionService:
        return ActionService(
            context=self.context,
            repository=ActionRepository(session, self.context),
            identity_guard=IdentityService(context=self.context, store=Mock()),
            connector=AppointmentActionConnector(self.appointments),
            approval_verifier=Approval(),
            audit=AuditService(session),
            outbox=OutboxService(session),
        )

    async def request(
        self,
        operation: str,
        arguments: dict[str, object],
        *,
        level: int = 2,
        customer: str = "customer",
    ) -> ActionRecord:
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            return await self.appointments.request_action(
                actions=self.actions(session),
                action_id=uuid4(),
                conversation_id=self.conversation,
                customer_ref=customer,
                operation="appointments." + operation,
                arguments=arguments,
                assessment=IdentityAssessment(
                    tenant_id=self.context.tenant_id,
                    customer_ref=customer,
                    achieved_level=IdentityLevel(level),
                    evidence_ids=(),
                    assessed_at=NOW,
                ),
            )

    async def confirm(
        self, action: ActionRecord, *, approve: bool = False
    ) -> ActionRecord:
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            actions = self.actions(session)
            confirmed = await actions.confirm(
                action_id=action.id,
                parameter_digest=action.parameter_digest,
                customer_ref=action.customer_ref,
                confirmed_at=NOW,
            )
            if approve:
                return await actions.approve_reference(
                    action_id=action.id,
                    parameter_digest=action.parameter_digest,
                    approval_reference="verified-approval",
                    approved_at=NOW,
                )
            return confirmed

    async def execute(self, action: ActionRecord) -> ActionOutcome:
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            return await self.actions(session).execute(
                action_id=action.id, executed_at=NOW
            )

    async def notifications(self, appointment_id: UUID) -> list[JobEnvelope]:
        async with self.sessions.begin() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id FROM public.outbox_jobs WHERE topic = 'appointments.notify' AND payload->>'appointment_id' = :id ORDER BY available_at, id"
                        ),
                        {"id": str(appointment_id)},
                    )
                )
                .scalars()
                .all()
            )
        return [
            JobEnvelope(
                job_id, self.context.tenant_id, "appointments.notify", appointment_id
            )
            for job_id in rows
        ]


@pytest.fixture
async def world(session_factory: async_sessionmaker[AsyncSession]) -> World:
    tenant_id, conversation = uuid4(), uuid4()
    context = TenantContext(tenant_id, uuid4(), "platform_admin", uuid4())
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants(id, slug, name) VALUES (:id, :slug, 'Task24')"
            ),
            {"id": tenant_id, "slug": f"task24-{tenant_id}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.integration_connections(id, tenant_id, connector_name, auth_kind) VALUES (:id, :tenant, 'google_calendar', 'OAUTH2')"
            ),
            {"id": CONNECTION, "tenant": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts(id, tenant_id, provider, waba_id, phone_number_id, status) VALUES (:id, :tenant, 'meta', 'task24-waba', 'task24-phone', 'active')"
            ),
            {"id": ACCOUNT, "tenant": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations(id, tenant_id, whatsapp_account_id, customer_wa_id) VALUES (:id, :tenant, :account, '573000000024')"
            ),
            {"id": conversation, "tenant": tenant_id, "account": ACCOUNT},
        )
    calendar = FakeCalendar()
    appointments = AppointmentsService(
        sessions=session_factory,
        context=context,
        calendar=lambda config: calendar,
        now=lambda: NOW,
    )
    await appointments.configure(configuration())
    variables = ("appointment_id", "service", "professional", "location", "start")
    await TemplateService(session_factory=session_factory, context=context).sync(
        whatsapp_account_id=ACCOUNT,
        templates=tuple(
            SyncedWhatsAppTemplate(
                provider_template_id=name,
                name=name,
                language="es_CO",
                status="APPROVED",
                category="UTILITY",
                variable_names=variables
                + (
                    ("attendance_confirmation", "reschedule_option")
                    if "reminder" in name
                    else ()
                ),
            )
            for name in (
                "appointment_confirmation",
                "appointment_reminder",
                "appointment_cancellation",
            )
        ),
    )
    return World(session_factory, context, conversation, calendar, appointments)


BOOK = {
    "service_id": "consultation",
    "professional_id": "professional",
    "location_id": "office",
    "start": "2026-09-01T14:15:00Z",
}


async def test_booking_race_replay_reschedule_approval_and_template_notifications(
    world: World,
) -> None:
    availability = await world.request(
        "check_availability",
        {"service_id": "consultation", "day": "2026-09-01"},
        level=0,
    )
    assert (await world.execute(availability)).result["data"]["held"] is False
    first = await world.request("create_appointment", BOOK, level=1)
    assert first.state == "AWAITING_CONFIRMATION"
    with pytest.raises(DomainError):
        await world.execute(first)
    second = await world.request("create_appointment", BOOK, level=1)
    await world.confirm(first)
    await world.confirm(second)
    outcomes = await asyncio.wait_for(
        asyncio.gather(world.execute(first), world.execute(second)), timeout=15
    )
    assert sorted(item.state for item in outcomes) == ["FAILED", "SUCCEEDED"]
    winner = next(item for item in outcomes if item.state == "SUCCEEDED")
    winning_action = first if winner.action_id == first.id else second
    appointment_id = UUID(winner.result["data"]["id"])
    assert world.calendar.writes == 1
    assert (await world.execute(winning_action)).result == winner.result
    assert world.calendar.writes == 1
    messages = await world.notifications(appointment_id)
    assert len(messages) == 2  # immediate confirmation + one reminder
    outbound = await prepare_appointment_notification(
        sessions=world.sessions, envelope=messages[0], now=NOW
    )
    assert outbound is not None
    assert (
        await prepare_appointment_notification(
            sessions=world.sessions, envelope=messages[0], now=NOW
        )
        == outbound
    )
    with pytest.raises(AppointmentUnavailable, match="appointment_not_found"):
        await world.request(
            "get_appointment", {"appointment_id": str(appointment_id)}, customer="other"
        )
    read = await world.request(
        "get_appointment", {"appointment_id": str(appointment_id)}, level=1
    )
    assert (await world.execute(read)).result["data"]["provider_status"] == "confirmed"
    with pytest.raises(DomainError, match="Identity"):
        await world.request(
            "reschedule_appointment",
            {"appointment_id": str(appointment_id), "start": "2026-09-01T16:15:00Z"},
            level=1,
        )
    move = await world.request(
        "reschedule_appointment",
        {"appointment_id": str(appointment_id), "start": "2026-09-01T16:15:00Z"},
    )
    await world.confirm(move)
    moved = await world.execute(move)
    assert moved.state == "SUCCEEDED" and world.calendar.writes == 2
    assert (
        await world.execute(move)
    ).result == moved.result and world.calendar.writes == 2
    assert (
        await prepare_appointment_notification(
            sessions=world.sessions, envelope=messages[1], now=NOW + timedelta(hours=2)
        )
        is None
    )
    async with world.sessions.begin() as session:
        assert (
            await session.scalar(
                text("SELECT status FROM public.outbound_messages WHERE id = :id"),
                {"id": outbound},
            )
            == "BLOCKED"
        )
    cancellation = await world.request(
        "request_cancellation",
        {"appointment_id": str(appointment_id), "reason": "Customer requested review"},
    )
    confirmed = await world.confirm(cancellation)
    assert confirmed.state == "AWAITING_APPROVAL"
    with pytest.raises(DomainError):
        await world.execute(cancellation)
    async with world.sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await world.actions(session).approve_reference(
            action_id=cancellation.id,
            parameter_digest=cancellation.parameter_digest,
            approval_reference="verified-approval",
            approved_at=NOW,
        )
    canceled = await world.execute(cancellation)
    assert (
        canceled.state == "SUCCEEDED"
        and canceled.result["data"]["status"] == "CANCELLATION_REQUESTED"
    )
    assert (
        canceled.result["data"]["cancellation_executed"] is False
        and world.calendar.writes == 2
    )


async def test_uncertain_write_is_not_replayed_and_tenant_reads_are_isolated(
    world: World,
) -> None:
    world.calendar.fail_after_write = True
    action = await world.request("create_appointment", BOOK)
    await world.confirm(action)
    result = await world.execute(action)
    assert result.state == "UNCERTAIN" and world.calendar.writes == 1
    assert (
        await world.execute(action)
    ).state == "UNCERTAIN" and world.calendar.writes == 1
    world.calendar.fail_after_write = False
    competing = await world.request("create_appointment", BOOK)
    await world.confirm(competing)
    assert (
        await world.execute(competing)
    ).state == "FAILED" and world.calendar.writes == 1
    async with world.sessions.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        await set_tenant_context(session, uuid4())
        for table in (
            "appointment_configurations",
            "appointments",
            "appointment_operations",
        ):
            assert (
                await session.scalar(text(f"SELECT count(*) FROM public.{table}")) == 0
            )
    async with world.appointments.transaction() as repository:
        await repository.scope()
        assert (
            await repository.session.scalar(
                text("SELECT count(*) FROM public.appointments")
            )
            == 0
        )
        assert (
            await repository.session.scalar(
                text("SELECT count(*) FROM public.appointment_operations")
            )
            == 2
        )
