from dataclasses import replace

from apps.backend.tests.approval_support import ApprovalHarness, EMAILS
from agents_factory.modules.approvals.execution import (
    ApprovalExecutionService,
    ApprovalNotificationBinding,
)
from agents_factory.modules.capabilities.orders.service import OrdersActionConnector
from agents_factory.modules.runtime.turn_service import Milestone2AgentSpecProvider


class Specs(Milestone2AgentSpecProvider):
    active = True

    async def get_active(self, *, tenant_id):
        spec = await super().get_active(tenant_id=tenant_id)
        return replace(
            spec,
            active=self.active,
            active_capabilities=frozenset({"orders", "appointments"}),
            permitted_tools=frozenset(
                {
                    "orders.request_order_cancellation",
                    "appointments.request_cancellation",
                }
            ),
        )


def executor(world, h, connector=None):
    specs = Specs()
    service = ApprovalExecutionService(
        world.sessions,
        agent_specs=lambda session, context: specs,
        connectors=connector
        or (lambda context, action: OrdersActionConnector(world.orders)),
        notifications={
            world.context.tenant_id: ApprovalNotificationBinding("approval_result")
        },
        now=lambda: h.clock,
    )
    return service, specs


async def approved(world):
    h = await ApprovalHarness.create(world)
    action, request = await h.request()
    tokens = await h.notices(request)
    command = await h.verification(tokens[EMAILS[0]])
    assert (await h.service.decide(command)).status == "RECORDED"
    service, specs = executor(world, h)
    return h, action, service, specs
