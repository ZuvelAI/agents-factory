"""Technical text only: no model, welcome composition or commercial tools."""

from dataclasses import replace
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.outbox import OutboxService
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.runtime.contracts import AgentTurnResult, RuntimeUsage
from agents_factory.modules.runtime.turn_service import _RuntimeTurnRepository
from .authorization import AudioAuthority


def fallback_text(error_code: str) -> str:
    if any(value in error_code for value in ("size", "duration", "output_limit")):
        return "Puedo procesar notas de voz de hasta 5 minutos y 10 MB. Envíame una nota más corta o escríbeme tu consulta."
    if "format" in error_code:
        return "Todavía no puedo procesar este formato de audio. Envíame una nota de voz de WhatsApp o escríbeme tu consulta."
    return "No pude procesar tu nota de voz. ¿Puedes enviarla de nuevo o escribirme tu consulta?"


class AudioFallbackService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        context: TenantContext,
        authority: AudioAuthority,
    ) -> None:
        self.factory, self.context, self.authority = factory, context, authority

    async def finalize(self, message_id: UUID, error_code: str) -> None:
        async with self.factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            snapshot = await self.authority.load(
                session, self.context, message_id, lock=True
            )
            if snapshot is None:
                return
            conversation = await session.scalar(
                text(
                    "SELECT conversation_id FROM public.messages WHERE tenant_id=:t AND id=:m"
                ),
                {"t": self.context.tenant_id, "m": message_id},
            )
            result = await _RuntimeTurnRepository(session).persist_assistant_reply(
                context=self.context,
                conversation_id=conversation,
                inbound_message_id=message_id,
                agent_spec=replace(
                    snapshot, first_contact_greeting=None, first_contact_since=None
                ),
                result=AgentTurnResult(
                    fallback_text(error_code), (), RuntimeUsage(0, 0, 0, 0, 0, 0), None
                ),
                awaiting_human_policy=AwaitingHumanPolicy.SILENT,
            )
            if result.created and result.message_id is not None:
                await OutboxService(session).enqueue(
                    context=self.context,
                    idempotency_key=f"outbound.text:{result.message_id}",
                    topic="outbound.text",
                    payload={
                        "aggregate_id": str(conversation),
                        "conversation_id": str(conversation),
                        "message_id": str(result.message_id),
                    },
                )
