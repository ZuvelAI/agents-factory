from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context

from .models import AgentOperationState


def operation_lock_key(tenant_id: UUID, agent_id: UUID) -> str:
    return f"agent-operation:{tenant_id}:{agent_id}"


class AgentOperationRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context

    async def lock(self, agent_id: UUID) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": operation_lock_key(self.context.tenant_id, agent_id)},
        )

    async def initialize(self, agent_id: UUID) -> None:
        await set_tenant_context(self.session, self.context.tenant_id)
        await self.session.execute(
            text(
                "INSERT INTO public.agent_operation_states (tenant_id,agent_instance_id) "
                "VALUES(:tenant,:agent) ON CONFLICT DO NOTHING"
            ),
            {"tenant": self.context.tenant_id, "agent": agent_id},
        )

    async def get(self, agent_id: UUID) -> AgentOperationState | None:
        await set_tenant_context(self.session, self.context.tenant_id)
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.agent_operation_states "
                        "WHERE tenant_id=:tenant AND agent_instance_id=:agent"
                    ),
                    {"tenant": self.context.tenant_id, "agent": agent_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else AgentOperationState.model_validate(dict(row))

    async def change(self, agent_id: UUID, *, enabled: bool) -> AgentOperationState:
        row = (
            (
                await self.session.execute(
                    text(
                        "UPDATE public.agent_operation_states SET enabled=:enabled, "
                        "revision=revision+1,updated_at=clock_timestamp(), "
                        "resumed_at=CASE WHEN :enabled THEN clock_timestamp() ELSE resumed_at END "
                        "WHERE tenant_id=:tenant AND agent_instance_id=:agent RETURNING *"
                    ),
                    {
                        "tenant": self.context.tenant_id,
                        "agent": agent_id,
                        "enabled": enabled,
                    },
                )
            )
            .mappings()
            .one()
        )
        return AgentOperationState.model_validate(dict(row))
