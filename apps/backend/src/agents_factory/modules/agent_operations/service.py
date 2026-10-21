from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.modules.agent_factory.publication_service import publication_problem
from agents_factory.modules.agent_factory.repository import AgentSpecRepository

from .models import AgentOperationState
from .repository import AgentOperationRepository


class AgentOperationService:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context
        self.repository = AgentOperationRepository(session, context)

    async def get_state(self, agent_id: UUID) -> AgentOperationState:
        state = await self.repository.get(agent_id)
        if (
            state is None
            or await AgentSpecRepository(self.session, self.context).get_instance(
                agent_id
            )
            is None
        ):
            raise publication_problem(
                "agent_operation_not_found", "Empresa o agente no encontrado.", 404
            )
        return state

    async def transition(
        self, *, agent_id: UUID, enabled: bool, expected_revision: int
    ) -> AgentOperationState:
        if self.context.actor_type != "platform_admin" or self.context.actor_id is None:
            raise publication_problem(
                "agent_operation_forbidden", "Operación no autorizada.", 403
            )
        await self.repository.lock(agent_id)
        current = await self.get_state(agent_id)
        if current.revision != expected_revision:
            raise publication_problem(
                "agent_operation_revision_conflict",
                "El estado cambió. Recarga antes de continuar.",
                409,
            )
        if current.enabled == enabled:
            return current
        changed = await self.repository.change(agent_id, enabled=enabled)
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.resumed" if enabled else "agent.paused",
            entity_type="agent_operation",
            entity_id=agent_id,
            payload={
                "enabled": enabled,
                "previous_revision": current.revision,
                "revision": changed.revision,
            },
        )
        return changed
