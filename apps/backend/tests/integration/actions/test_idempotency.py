from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.actions.models import ActionRecord, PreconditionDecision
from agents_factory.modules.actions.repository import ActionRepository
from agents_factory.modules.actions.service import ActionService
from agents_factory.modules.identity.models import (
    AuthorizationDecision,
    IdentityAssessment,
    IdentityLevel,
)
from agents_factory.modules.integrations.contracts import (
    ConnectorRequest,
    ConnectorResult,
)


NOW = datetime(2026, 8, 29, 18, tzinfo=UTC)
TENANT_ID = UUID("10000000-0000-0000-0000-000000000215")
ACCOUNT_ID = UUID("20000000-0000-0000-0000-000000000215")
CONVERSATION_ID = UUID("30000000-0000-0000-0000-000000000215")
BINDING_ID = UUID("40000000-0000-0000-0000-000000000215")


class Guard:
    def require_for_action(self, **kwargs: object) -> None:
        _ = kwargs


class Connector:
    calls = 0

    def is_safe_read(self, operation: str) -> bool:
        return operation == "orders.get_status"

    async def revalidate(self, action: ActionRecord) -> PreconditionDecision:
        _ = action
        return PreconditionDecision(valid=True, reason_code="current")

    async def execute(self, request: ConnectorRequest) -> ConnectorResult:
        self.calls += 1
        return ConnectorResult(
            operation=request.operation,
            status="SUCCEEDED",
            data={"status": "processing"},
        )


class ApprovalGuard:
    async def verify(self, **kwargs: object) -> bool:
        _ = kwargs
        return True


@pytest.mark.asyncio
async def test_duplicate_action_and_execute_are_idempotent_and_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO public.tenants (id, slug, name) "
                "VALUES (:tenant_id, 'task15', 'Task 15')"
            ),
            {"tenant_id": TENANT_ID},
        )
        await session.execute(
            text(
                "INSERT INTO public.whatsapp_accounts "
                "(id, tenant_id, provider, waba_id, phone_number_id, status) "
                "VALUES (:id, :tenant_id, 'meta', 'task15-waba', "
                "'task15-phone', 'active')"
            ),
            {"id": ACCOUNT_ID, "tenant_id": TENANT_ID},
        )
        await session.execute(
            text(
                "INSERT INTO public.conversations "
                "(id, tenant_id, whatsapp_account_id, customer_wa_id) "
                "VALUES (:id, :tenant_id, :account_id, '573000000015')"
            ),
            {"id": CONVERSATION_ID, "tenant_id": TENANT_ID, "account_id": ACCOUNT_ID},
        )

    connector = Connector()
    action_id = uuid4()
    context = TenantContext(
        tenant_id=TENANT_ID,
        actor_id=None,
        actor_type="system",
        correlation_id=uuid4(),
    )
    async with session_factory.begin() as session:
        await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        actions = ActionService(
            context=context,
            repository=ActionRepository(session, context),
            identity_guard=Guard(),
            connector=connector,
            approval_verifier=ApprovalGuard(),
            audit=AuditService(session),
            outbox=OutboxService(session),
        )
        arguments = dict(
            action_id=action_id,
            conversation_id=CONVERSATION_ID,
            customer_ref="customer",
            capability="orders",
            action_type="orders.get_status",
            risk="LOW",
            minimum_identity_level=IdentityLevel.LEVEL_1,
            tenant_policy=None,
            assessment=IdentityAssessment(
                tenant_id=TENANT_ID,
                customer_ref="customer",
                achieved_level=IdentityLevel.LEVEL_1,
                evidence_ids=(),
                assessed_at=NOW,
            ),
            authorization=AuthorizationDecision(
                tenant_id=TENANT_ID,
                customer_ref="customer",
                resource_type="order",
                resource_id="order-1",
                action="orders.get_status",
                allowed=True,
                reason_code="owner",
            ),
            resource_type="order",
            resource_id="order-1",
            parameters={"order_id": "order-1"},
            approval_route_ref=None,
            connector_binding_id=BINDING_ID,
            connector_name="woocommerce",
            requested_at=NOW,
        )
        first = await actions.request(**arguments)  # type: ignore[arg-type]
        duplicate = await actions.request(**arguments)  # type: ignore[arg-type]
        assert first.id == duplicate.id
        first_outcome = await actions.execute(action_id=action_id, executed_at=NOW)
        second_outcome = await actions.execute(action_id=action_id, executed_at=NOW)

        assert first_outcome.state == second_outcome.state == "SUCCEEDED"
        assert connector.calls == 1
        audit_events = (
            (
                await session.execute(
                    text(
                        "SELECT event_type FROM public.audit_events "
                        "WHERE entity_id = :id"
                    ),
                    {"id": action_id},
                )
            )
            .scalars()
            .all()
        )
        assert sorted(audit_events) == ["action.revalidated", "action.succeeded"]
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM public.outbox_jobs WHERE topic = 'action.result'"
                )
            )
            == 1
        )
