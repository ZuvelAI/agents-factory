from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.account_lifecycle import lock_account_lifecycle
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.models import AgentSpecVersion


class AccountAgentBinding(BaseModel):
    tenant_id: UUID
    whatsapp_account_id: UUID
    agent_instance_id: UUID
    version_id: UUID
    revision: int
    updated_at: datetime


class AccountAgentBindingRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context

    async def get_for_account(self, account_id: UUID) -> AccountAgentBinding | None:
        await set_tenant_context(self.session, self.context.tenant_id)
        result = await self.session.execute(
            text(
                "SELECT * FROM public.account_agent_bindings "
                "WHERE tenant_id=:tenant AND whatsapp_account_id=:account"
            ),
            {"tenant": self.context.tenant_id, "account": account_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else AccountAgentBinding(**row)

    async def bind(
        self,
        account_id: UUID,
        version: AgentSpecVersion,
        *,
        expected_revision: int,
        action: Literal["PUBLISH", "ROLLBACK"],
    ) -> AccountAgentBinding:
        from agents_factory.modules.agent_factory.publication_service import (
            publication_problem,
        )

        await set_tenant_context(self.session, self.context.tenant_id)
        await lock_account_lifecycle(self.session, self.context.tenant_id, account_id)
        current = await self.get_for_account(account_id)
        if (0 if current is None else current.revision) != expected_revision:
            raise publication_problem(
                "stale_account_binding", "Reload the current account binding"
            )
        if version.tenant_id != self.context.tenant_id or version.state != "PRODUCTION":
            raise publication_problem(
                "invalid_account_binding",
                "Only tenant production versions can be assigned",
            )
        parameters = {
            "tenant": self.context.tenant_id,
            "account": account_id,
            "instance": version.agent_instance_id,
            "version": version.id,
            "revision": expected_revision + 1,
        }
        await self.session.execute(
            text(
                "INSERT INTO public.account_agent_bindings "
                "(tenant_id,whatsapp_account_id,agent_instance_id,version_id,revision) "
                "VALUES(:tenant,:account,:instance,:version,:revision) ON CONFLICT(tenant_id,whatsapp_account_id) DO UPDATE "
                "SET agent_instance_id=EXCLUDED.agent_instance_id,version_id=EXCLUDED.version_id,revision=EXCLUDED.revision,updated_at=now()"
            ),
            parameters,
        )
        await self.session.execute(
            text(
                "INSERT INTO public.account_agent_binding_history "
                "(id,tenant_id,whatsapp_account_id,agent_instance_id,version_id,revision,action) "
                "VALUES(:id,:tenant,:account,:instance,:version,:revision,:action)"
            ),
            parameters | {"id": uuid4(), "action": action},
        )
        binding = await self.get_for_account(account_id)
        if binding is None:
            raise RuntimeError("account binding was not persisted")
        return binding
