from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.backend.tests.order_support import WooFixture, SheetFixture, ADDRESS
from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.cases.contracts import CaseReceipt, UnavailableCases
from agents_factory.modules.capabilities.orders.issues import IssueNeedsInformation
from agents_factory.modules.capabilities.orders.models import OrdersBinding
from agents_factory.modules.capabilities.orders.service import (
    OrderCustomer,
    OrderUnavailable,
    OrdersActionConnector,
    OrdersService,
)
from agents_factory.modules.capabilities.orders.tools import OrdersToolSession
from agents_factory.modules.identity.models import IdentityAssessment, IdentityLevel
from agents_factory.modules.identity.service import IdentityService
from agents_factory.modules.integrations.orders import CustomerMatch, READS, WRITES
from agents_factory.modules.runtime.contracts import ToolInvocationContext


class Customers:
    level = 2

    async def resolve(self, *, context, customer_ref, binding_id, action_id):
        return OrderCustomer(
            IdentityAssessment(
                tenant_id=context.tenant_id,
                customer_ref=customer_ref,
                achieved_level=IdentityLevel(self.level),
                evidence_ids=(),
                assessed_at=datetime.now(UTC),
            ),
            CustomerMatch(customer_id="7" if customer_ref == "customer" else "9"),
        )


class Approval:
    async def verify(
        self, *, route_ref, approval_reference, action_id, parameter_digest
    ):
        return (
            route_ref == "orders-approvals"
            and approval_reference == "verified-approval"
        )


class Cases:
    available = True

    def __init__(self):
        self.records = {}
        self.intakes = []

    async def create_or_update(self, *, context, intake):
        self.intakes.append(intake)
        if intake.deduplication_key in self.records:
            return self.records[intake.deduplication_key].model_copy(
                update={"reused": True}
            )
        receipt = CaseReceipt(
            case_id=uuid4(),
            tenant_id=context.tenant_id,
            customer_ref=intake.customer_ref,
            deduplication_key=intake.deduplication_key,
            status="OPEN",
        )
        self.records[intake.deduplication_key] = receipt
        return receipt


class Evidence:
    def __init__(self):
        self.allowed_id = uuid4()

    async def allowed(self, *, context, customer_ref, evidence_id):
        return customer_ref == "customer" and evidence_id == self.allowed_id


@dataclass
class World:
    sessions: async_sessionmaker[AsyncSession]
    context: TenantContext
    conversation: UUID
    fixtures: dict
    bindings: dict
    customers: Customers
    cases: Cases
    evidence: Evidence
    orders: OrdersService

    def actions(self, session):
        return ActionService(
            context=self.context,
            repository=ActionRepository(session, self.context),
            identity_guard=IdentityService(context=self.context, store=Mock()),
            connector=OrdersActionConnector(self.orders),
            approval_verifier=Approval(),
            audit=AuditService(session),
            outbox=OutboxService(session),
        )

    async def request(
        self, binding_id, operation, arguments, *, action_id=None, customer="customer"
    ):
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            return await self.orders.request_action(
                actions=self.actions(session),
                action_id=action_id or uuid4(),
                conversation_id=self.conversation,
                customer_ref=customer,
                binding_id=binding_id,
                operation=operation,
                arguments=arguments,
            )

    async def confirm(self, action, *, approve=False, wrong_digest=False):
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            actions = self.actions(session)
            confirmed = await actions.confirm(
                action_id=action.id,
                parameter_digest="0" * 64 if wrong_digest else action.parameter_digest,
                customer_ref="customer",
            )
            if approve:
                with pytest.raises(DomainError):
                    await actions.approve_reference(
                        action_id=action.id,
                        parameter_digest=action.parameter_digest,
                        approval_reference="model-supplied-approval",
                    )
                return await actions.approve_reference(
                    action_id=action.id,
                    parameter_digest=action.parameter_digest,
                    approval_reference="verified-approval",
                )
            return confirmed

    async def execute(self, action):
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            return await self.actions(session).execute(action_id=action.id)


@pytest.fixture
async def order_world(session_factory):
    tenant, conversation, account = uuid4(), uuid4(), uuid4()
    context = TenantContext(tenant, uuid4(), "platform_admin", uuid4())
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants(id, slug, name) VALUES (:id, :slug, 'Task26')"
            ),
            {"id": tenant, "slug": f"task26-{tenant}"},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts(id, tenant_id, provider, waba_id, phone_number_id, status) VALUES (:id, :tenant, 'meta', :waba, :phone, 'active')"
            ),
            {
                "id": account,
                "tenant": tenant,
                "waba": str(uuid4()),
                "phone": str(uuid4()),
            },
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations(id, tenant_id, whatsapp_account_id, customer_wa_id) VALUES (:id, :tenant, :account, '573000000026')"
            ),
            {"id": conversation, "tenant": tenant, "account": account},
        )
    fixtures, bindings = {}, {}
    for connector, fixture in (
        ("woocommerce", WooFixture()),
        ("google_sheets", SheetFixture()),
    ):
        fixture.binding = replace(fixture.binding, tenant_id=tenant)
        fixture.adapter.binding = fixture.binding
        if isinstance(fixture, SheetFixture):
            fixture.adapter.native.binding = replace(
                fixture.adapter.native.binding, tenant_id=tenant
            )
        fixtures[fixture.binding.binding_id] = fixture
        bindings[fixture.binding.binding_id] = OrdersBinding(
            tenant_id=tenant,
            binding_id=fixture.binding.binding_id,
            connection_id=uuid4(),
            connector=connector,
            resource=fixture.resource,
            allow_writes=True,
            approval_route_ref="orders-approvals",
        )
    customers, cases, evidence = Customers(), Cases(), Evidence()
    orders = OrdersService(
        sessions=session_factory,
        context=context,
        bindings=bindings.get,
        customers=customers,
        connectors=lambda binding: fixtures[binding.binding_id].adapter,
        cases=cases,
        evidence=evidence,
    )
    return World(
        session_factory,
        context,
        conversation,
        fixtures,
        bindings,
        customers,
        cases,
        evidence,
        orders,
    )


async def test_order_action_matrix_provider_parity_exact_confirmation_and_replay(
    order_world,
):
    world = order_world
    first = next(iter(world.bindings))
    world.customers.level = 0
    with pytest.raises(OrderUnavailable, match="identity_required"):
        await world.request(first, READS[1], {"order_id": "42"})
    assert not world.fixtures[first].calls
    world.customers.level = 1
    with pytest.raises(OrderUnavailable, match="identity_required"):
        await world.request(first, WRITES[0], {"order_id": "42", "address": ADDRESS})
    with pytest.raises(OrderUnavailable, match="order_not_found"):
        await world.request(first, READS[1], {"order_id": "42"}, customer="other")
    results = []
    for binding_id in world.bindings:
        rows = []
        for operation in READS:
            action = await world.request(binding_id, operation, {"order_id": "42"})
            assert action.risk == "LOW" and action.required_identity_level == 1
            outcome = await world.execute(action)
            assert outcome.state == "SUCCEEDED"
            data = dict(outcome.result["data"])
            data.pop("version", None)
            if "orders" in data:
                data["orders"] = [
                    {k: v for k, v in item.items() if k != "version"}
                    for item in data["orders"]
                ]
            rows.append(data)
        results.append(rows)
    assert results[0] == results[1]
    world.customers.level = 2
    for binding_id, fixture in world.fixtures.items():
        for operation, update in zip(
            WRITES,
            (
                {"address": ADDRESS},
                {"contact": {"phone": "+571111111111"}},
                {"note": "Customer follow-up"},
                {"reason": "Customer request"},
            ),
        ):
            args = {"order_id": "42", **update}
            action = await world.request(binding_id, operation, args)
            assert (
                action.required_identity_level == 2
                and action.state == "AWAITING_CONFIRMATION"
            )
            assert action.risk == ("HIGH" if operation == WRITES[3] else "MEDIUM")
            with pytest.raises(DomainError):
                await world.execute(action)
            with pytest.raises(DomainError):
                await world.confirm(action, wrong_digest=True)
            await world.confirm(action, approve=operation == WRITES[3])
            outcome = await world.execute(action)
            assert outcome.state == "SUCCEEDED", outcome
            count = len(fixture.calls)
            assert (await world.execute(action)).result == outcome.result
            assert (
                await world.request(binding_id, operation, args, action_id=action.id)
            ).id == action.id
            assert len(fixture.calls) == count
            if operation == WRITES[3]:
                assert outcome.result["data"]["cancellation_executed"] is False
    assert len(world.fixtures[first].notes) == 1
    assert world.fixtures[first].order["status"] == "processing"


async def test_crash_receipt_uncertainty_outage_and_approval_revalidation(order_world):
    world = order_world
    binding_id = next(iter(world.bindings))
    fixture = world.fixtures[binding_id]
    action = await world.request(
        binding_id, WRITES[2], {"order_id": "42", "note": "One external effect"}
    )
    await world.confirm(action)
    native = fixture.adapter

    class CrashAfterWrite:
        async def execute(self, request):
            result = await native.execute(request)
            if request.operation == WRITES[2]:
                raise asyncio.CancelledError()
            return result

    fixture.adapter = CrashAfterWrite()
    with pytest.raises(asyncio.CancelledError):
        await world.execute(action)
    assert len(fixture.notes) == 1
    fixture.adapter = native
    calls = len(fixture.calls)
    uncertain = await world.execute(action)
    assert uncertain.state == "UNCERTAIN" and len(fixture.calls) == calls
    assert (await world.execute(action)).state == "UNCERTAIN"
    cancellation = await world.request(
        binding_id, WRITES[3], {"order_id": "42", "reason": "Before shipment"}
    )
    await world.confirm(cancellation, approve=True)
    fixture.order["status"] = "completed"
    assert (await world.execute(cancellation)).state == "FAILED"
    assert not any(req.method == "PUT" for req in fixture.calls)
    world.bindings[binding_id] = world.bindings[binding_id].model_copy(
        update={"enabled": False}
    )
    async with world.sessions.begin() as session:
        context = ToolInvocationContext(
            tenant_id=world.context.tenant_id,
            conversation_id=world.conversation,
            inbound_message_id=uuid4(),
            correlation_id=uuid4(),
        )
        tool_session = OrdersToolSession(
            context=context,
            orders=world.orders,
            actions=world.actions(session),
            binding_id=binding_id,
            customer_ref="customer",
        )
        assert tool_session.tools() == ()
    healthy = next(key for key in world.bindings if key != binding_id)
    assert (
        await world.execute(await world.request(healthy, READS[1], {"order_id": "42"}))
    ).state == "SUCCEEDED"


async def test_issue_intake_contract_evidence_deduplication_and_fail_closed_cases(
    order_world,
):
    world = order_world
    world.customers.level = 1
    binding = next(iter(world.bindings))
    with pytest.raises(IssueNeedsInformation) as missing:
        await world.request(
            binding, "orders.create_claim", {"issue_type": "damaged_product"}
        )
    assert {"description", "item_ids", "evidence_ids"}.issubset(missing.value.fields)
    for issue in (
        "missing_order",
        "wrong_product",
        "damaged_product",
        "delivery_delay",
        "create_claim",
    ):
        args = {
            "issue_type": issue,
            "description": "Customer reports a problem",
            "order_id": "42",
            "item_ids": ["1"],
            "evidence_ids": [str(world.evidence.allowed_id)]
            if issue == "damaged_product"
            else [],
        }
        action = await world.request(binding, "orders.create_claim", args)
        assert action.required_identity_level == 1 and action.confirmation_required
        await world.confirm(action)
        outcome = await world.execute(action)
        assert (
            outcome.state == "SUCCEEDED"
            and outcome.result["data"]["resolution_promised"] is False
        )
        count = len(world.cases.intakes)
        assert (await world.execute(action)).result == outcome.result
        assert len(world.cases.intakes) == count
        duplicate = await world.request(binding, "orders.create_claim", args)
        await world.confirm(duplicate)
        result = await world.execute(duplicate)
        assert result.result["data"]["case_id"] == outcome.result["data"]["case_id"]
        assert result.result["data"]["reused"] is True
    assert len(world.cases.records) == 5
    with pytest.raises(OrderUnavailable, match="evidence_unavailable"):
        await world.request(
            binding,
            "orders.create_claim",
            {
                "issue_type": "damaged_product",
                "order_id": "42",
                "description": "Issue",
                "item_ids": ["1"],
                "evidence_ids": [str(uuid4())],
            },
        )
    world.orders.cases = UnavailableCases()
    with pytest.raises(OrderUnavailable, match="case_creation_unavailable"):
        await world.request(
            binding,
            "orders.create_claim",
            {"issue_type": "create_claim", "description": "Issue", "order_id": "42"},
        )
