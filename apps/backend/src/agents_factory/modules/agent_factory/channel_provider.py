from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.agent_factory.approved_knowledge import (
    ApprovedKnowledgeRepository,
)
from agents_factory.modules.agent_factory.channel_binding import (
    AccountAgentBindingRepository,
)
from agents_factory.modules.agent_factory.repository import (
    AgentSpecRepository,
    ProductionAgentSpecProvider,
)
from agents_factory.modules.runtime.contracts import AgentSpecSnapshot
from agents_factory.modules.runtime.turn_service import AgentSpecProvider


class ConversationAgentSpecProvider:
    def __init__(
        self,
        session: AsyncSession,
        context: TenantContext,
        conversation_id: UUID,
        legacy_provider: AgentSpecProvider,
        *,
        code_digest: str | None,
        compatible_versions: dict[UUID, str] | None = None,
    ):
        self.session, self.context, self.conversation_id = (
            session,
            context,
            conversation_id,
        )
        self.legacy_provider, self.code_digest = legacy_provider, code_digest
        self.compatible_versions = dict(compatible_versions or {})

    async def get_active(self, *, tenant_id: UUID) -> AgentSpecSnapshot | None:
        if tenant_id != self.context.tenant_id:
            raise RuntimeError("conversation agent tenant mismatch")
        await set_tenant_context(self.session, tenant_id)
        account_id = await self.session.scalar(
            text(
                "SELECT whatsapp_account_id FROM public.conversations "
                "WHERE tenant_id=:tenant AND id=:conversation"
            ),
            {"tenant": tenant_id, "conversation": self.conversation_id},
        )
        if account_id is None:
            return None
        binding = await AccountAgentBindingRepository(
            self.session, self.context
        ).get_for_account(account_id)
        if binding is None:
            return await self.legacy_provider.get_active(tenant_id=tenant_id)
        version = await AgentSpecRepository(self.session, self.context).get_version(
            binding.version_id
        )
        if (
            version is None
            or version.state != "PRODUCTION"
            or version.agent_instance_id != binding.agent_instance_id
            or self.code_digest is None
            or (
                version.configuration.code_digest != self.code_digest
                and self.compatible_versions.get(version.id)
                != version.configuration.code_digest
            )
            or version.configuration.approved_business_context is None
        ):
            raise RuntimeError("published account agent integrity failed")
        knowledge = await ApprovedKnowledgeRepository(
            self.session, self.context
        ).get_by_digest(version.configuration.knowledge.digest)
        if (
            knowledge is None
            or knowledge.approved_summary
            != version.configuration.approved_business_context.approved_summary
        ):
            raise RuntimeError("published account knowledge integrity failed")
        snapshot = await ProductionAgentSpecProvider(
            self.session,
            agent_instance_id=binding.agent_instance_id,
            version_id=binding.version_id,
        ).get_active(tenant_id=tenant_id)
        if snapshot is None:
            raise RuntimeError("published account agent deployment is missing")
        await AuditService(self.session).record(
            context=self.context,
            event_type="agent.account_snapshot_selected",
            entity_type="conversation",
            entity_id=self.conversation_id,
            payload={"version_id": str(snapshot.id), "digest": snapshot.digest},
        )
        return snapshot
