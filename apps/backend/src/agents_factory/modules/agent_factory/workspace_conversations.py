"""Read-only conversation use cases, independent of current page and account bindings."""

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from agents_factory.database import set_tenant_context
from .publication_service import publication_problem
from .workspace_cursor import (
    decode_activity_cursor,
    encode_activity_cursor,
    decode_cursor,
    encode_cursor,
)
from .workspace_conversation_repository import WorkspaceConversationRepository
from .workspace_conversation_models import (
    ConversationPage,
    ConversationSummary,
    MessagePage,
    OperationalMessage,
)


class WorkspaceConversationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = WorkspaceConversationRepository(session)

    async def _scope(self, tenant_id: UUID) -> None:
        await set_tenant_context(self.session, tenant_id)
        if not await self.repository.exists("tenant", tenant_id, tenant_id):
            raise publication_problem(
                "workspace_not_found", "Empresa no encontrada.", 404
            )

    async def list_conversations(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None = None,
        account_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ConversationPage:
        await self._scope(tenant_id)
        for kind, id in [("agent", agent_id), ("account", account_id)]:
            if id is not None and not await self.repository.exists(kind, tenant_id, id):
                raise publication_problem(
                    "workspace_not_found", "Filtro no encontrado en esta empresa.", 404
                )
        at, id = decode_activity_cursor(cursor)
        rows = await self.repository.conversations(
            tenant=tenant_id,
            agent=agent_id,
            account=account_id,
            before_at=at,
            before_id=id,
            limit=limit + 1,
        )
        return ConversationPage(
            items=[ConversationSummary(**r) for r in rows[:limit]],
            next_cursor=encode_activity_cursor(
                rows[limit - 1]["last_activity_at"], rows[limit - 1]["id"]
            )
            if len(rows) > limit
            else None,
        )

    async def get_conversation(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        agent_id: UUID | None = None,
        account_id: UUID | None = None,
    ) -> ConversationSummary:
        await self._scope(tenant_id)
        rows = await self.repository.conversations(
            tenant=tenant_id,
            agent=agent_id,
            account=account_id,
            selected=conversation_id,
            limit=1,
        )
        if not rows:
            raise publication_problem(
                "workspace_not_found",
                "Conversación no encontrada para estos filtros.",
                404,
            )
        return ConversationSummary(**rows[0])

    async def list_messages(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        cursor: str | None = None,
        limit: int = 20,
    ) -> MessagePage:
        await self._scope(tenant_id)
        if not await self.repository.exists("conversation", tenant_id, conversation_id):
            raise publication_problem(
                "workspace_not_found", "Conversación no encontrada.", 404
            )
        after = decode_cursor(cursor)
        sequence = (
            await self.repository.message_sequence(tenant_id, conversation_id, after)
            if after
            else None
        )
        if after and sequence is None:
            raise publication_problem(
                "invalid_workspace_cursor", "Cursor de mensajes inválido.", 422
            )
        rows = await self.repository.messages(
            tenant=tenant_id,
            conversation=conversation_id,
            after=after,
            sequence=sequence,
            limit=limit + 1,
        )
        return MessagePage(
            items=[OperationalMessage(**r) for r in reversed(rows[:limit])],
            next_cursor=encode_cursor(rows[limit - 1]["id"])
            if len(rows) > limit
            else None,
        )
