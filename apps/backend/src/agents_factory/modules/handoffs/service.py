from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from agents_factory.modules.conversations.models import AwaitingHumanPolicy
from agents_factory.modules.conversations.service import ConversationService
from agents_factory.modules.handoffs.models import (
    HandoffConfiguration,
    HandoffError,
    HandoffReason,
    HandoffRecord,
    SurfaceBinding,
)
from agents_factory.modules.handoffs.policy import escalation_reason, waiting_copy
from agents_factory.modules.handoffs.surfaces import (
    HumanSurfaceRegistry,
    validate_account,
)


def require_backend(context: TenantContext, *, admin: bool = False) -> None:
    if context.actor_id is None or context.actor_type not in (
        {"platform_admin"} if admin else {"platform_admin", "system"}
    ):
        raise HandoffError("handoff_backend_required", 403)


class HandoffService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        surfaces: HumanSurfaceRegistry,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions, self.surfaces = sessions, surfaces
        self.now = now or (lambda: datetime.now(UTC))

    @asynccontextmanager
    async def transaction(self, context: TenantContext) -> AsyncIterator[AsyncSession]:
        require_backend(context)
        async with self.sessions.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(session, context.tenant_id)
            yield session

    async def configure(
        self,
        *,
        context: TenantContext,
        account_id: UUID,
        configuration: HandoffConfiguration,
        expected_revision: int = 0,
    ) -> int:
        require_backend(context, admin=True)
        async with self.transaction(context) as session:
            account = await self._account(session, context, account_id)
        if configuration.enabled:
            assert configuration.surface is not None
            await self.surfaces.verify(
                tenant_id=context.tenant_id,
                account=dict(account),
                binding=configuration.surface,
            )
        async with self.transaction(context) as session:
            # Serialize configurations on their account; no network inside locks.
            account = await self._account(session, context, account_id, lock=True)
            if configuration.enabled:
                assert configuration.surface is not None
                validate_account(dict(account), configuration.surface)
            old = await self._config(session, context, account_id)
            if (old["revision"] if old else 0) != expected_revision:
                raise HandoffError("handoff_configuration_conflict")
            configuration_id = old["id"] if old else new_uuid7()
            revision = expected_revision + 1
            await session.execute(
                text(
                    "INSERT INTO public.handoff_configurations "
                    "(id,tenant_id,whatsapp_account_id,revision,configuration) "
                    "VALUES (:id,:tenant,:account,:revision,:configuration) "
                    "ON CONFLICT (tenant_id,whatsapp_account_id) DO UPDATE SET "
                    "revision=excluded.revision, configuration=excluded.configuration"
                ).bindparams(bindparam("configuration", type_=JSONB)),
                {
                    "id": configuration_id,
                    "tenant": context.tenant_id,
                    "account": account_id,
                    "revision": revision,
                    "configuration": configuration.model_dump(mode="json"),
                },
            )
            await AuditService(session).record(
                context=context,
                event_type="handoff.configured",
                entity_type="handoff_configuration",
                entity_id=configuration_id,
                payload={"revision": revision, "enabled": configuration.enabled},
            )
            return revision

    async def request(
        self,
        *,
        context: TenantContext,
        conversation_id: UUID,
        reason: HandoffReason,
    ) -> HandoffRecord:
        require_backend(context)
        async with self.transaction(context) as session:
            conversation = await self._conversation(session, context, conversation_id)
            old = await self._live(session, context, conversation_id)
            if old:
                return HandoffRecord.model_validate(dict(old))
            config = await self._config(
                session, context, conversation["whatsapp_account_id"]
            )
            if config is None:
                raise HandoffError("human_surface_not_configured")
            configuration = HandoffConfiguration.model_validate(config["configuration"])
            if not configuration.enabled or configuration.surface is None:
                raise HandoffError("live_handoff_disabled")
            account = await self._account(
                session, context, conversation["whatsapp_account_id"]
            )
        # Adapter verifies both human routing and authenticated event capability.
        await self.surfaces.verify(
            tenant_id=context.tenant_id,
            account=dict(account),
            binding=configuration.surface,
        )
        async with self.transaction(context) as session:
            conversation = await self._conversation(
                session, context, conversation_id, lock=True
            )
            old = await self._live(session, context, conversation_id)
            if old:
                return HandoffRecord.model_validate(dict(old))
            if conversation["control_state"] != "AI_ACTIVE":
                raise HandoffError("conversation_not_ai_active")
            account = await self._account(
                session, context, conversation["whatsapp_account_id"], lock=True
            )
            current = await self._config(
                session, context, conversation["whatsapp_account_id"], lock=True
            )
            if current is None or current["revision"] != config["revision"]:
                raise HandoffError("handoff_configuration_conflict")
            validate_account(dict(account), configuration.surface)
            now, handoff_id, notice_id = self.now(), new_uuid7(), new_uuid7()
            await session.execute(
                text(
                    "INSERT INTO public.messages (id,tenant_id,conversation_id,direction,sender_type,"
                    "message_type,content,provider_timestamp,arrival_sequence) "
                    "SELECT :id,:tenant,:conversation,'outbound','system','text',:content,:now,"
                    "coalesce(max(arrival_sequence),0)+1 FROM public.messages "
                    "WHERE tenant_id=:tenant AND conversation_id=:conversation"
                ).bindparams(bindparam("content", type_=JSONB)),
                {
                    "id": notice_id,
                    "tenant": context.tenant_id,
                    "conversation": conversation_id,
                    "content": {"text": waiting_copy(configuration, now)},
                    "now": now,
                },
            )
            row = (
                (
                    await session.execute(
                        text(
                            "INSERT INTO public.handoffs (id,tenant_id,conversation_id,status,reason,configuration,"
                            "notice_message_id,requested_at,last_activity_at) VALUES "
                            "(:id,:tenant,:conversation,'REQUESTED',:reason,:configuration,:notice,:now,:now) RETURNING *"
                        ).bindparams(bindparam("configuration", type_=JSONB)),
                        {
                            "id": handoff_id,
                            "tenant": context.tenant_id,
                            "conversation": conversation_id,
                            "reason": reason.value,
                            "configuration": configuration.model_dump(mode="json"),
                            "notice": notice_id,
                            "now": now,
                        },
                    )
                )
                .mappings()
                .one()
            )
            await self._control(session, context).request_handoff(
                conversation_id=conversation_id, reason=reason.value
            )
            await AuditService(session).record(
                context=context,
                event_type="handoff.requested",
                entity_type="handoff",
                entity_id=handoff_id,
                payload={
                    "reason": reason.value,
                    "surface": configuration.surface.surface.value,
                },
            )
            await OutboxService(session).enqueue(
                context=context,
                topic="outbound.text",
                idempotency_key=f"outbound.text:{notice_id}",
                payload={
                    "aggregate_id": str(conversation_id),
                    "conversation_id": str(conversation_id),
                    "message_id": str(notice_id),
                },
            )
            return HandoffRecord.model_validate(dict(row))

    async def inspect_inbound(
        self,
        *,
        context: TenantContext,
        conversation_id: UUID,
        message_id: UUID,
    ) -> None:
        """Worker admission uses durable customer text, not job/model flags."""
        async with self.transaction(context) as session:
            body = await session.scalar(
                text(
                    "SELECT content->>'text' FROM public.messages WHERE tenant_id=:tenant "
                    "AND conversation_id=:conversation AND id=:message AND direction='inbound' "
                    "AND sender_type='customer' AND message_type='text'"
                ),
                {
                    "tenant": context.tenant_id,
                    "conversation": conversation_id,
                    "message": message_id,
                },
            )
        reason = escalation_reason(customer_text=body or "")
        if reason is None:
            return
        try:
            await self.request(
                context=context, conversation_id=conversation_id, reason=reason
            )
        except HandoffError as error:
            # No fabricated handoff when unavailable; normal AI may explain limitations.
            async with self.transaction(context) as session:
                await AuditService(session).record(
                    context=context,
                    event_type="handoff.request_denied",
                    entity_type="conversation",
                    entity_id=conversation_id,
                    payload={"code": error.code},
                )

    async def handle_event(
        self,
        *,
        context: TenantContext,
        binding: SurfaceBinding,
        event_ref: str,
    ) -> HandoffRecord:
        """Server-only adapter entry point. No endpoint accepts raw event claims."""
        require_backend(context)
        event = await self.surfaces.event(binding, event_ref)
        if (
            event.tenant_id != context.tenant_id
            or event.occurred_at > self.now() + timedelta(minutes=1)
        ):
            raise HandoffError("human_event_scope_invalid")
        async with self.transaction(context) as session:
            conversation = await self._conversation(
                session, context, event.conversation_id, lock=True
            )
            row = await self._record(session, context, event.handoff_id)
            if (
                row is None
                or row["conversation_id"] != event.conversation_id
                or conversation["whatsapp_account_id"] != event.whatsapp_account_id
            ):
                raise HandoffError("human_event_scope_invalid")
            record = HandoffRecord.model_validate(dict(row))
            if (
                record.configuration.surface != binding
                or event.occurred_at < record.requested_at
            ):
                raise HandoffError("human_event_scope_invalid")
            if record.status == "CLOSED" or event.sequence <= record.event_sequence:
                await AuditService(session).record(
                    context=context,
                    event_type="handoff.event_ignored",
                    entity_type="handoff",
                    entity_id=record.id,
                    payload={"event_id": event.event_id, "sequence": event.sequence},
                )
                return record
            if event.kind == "ACTIVITY" and record.status != "ACTIVE":
                raise HandoffError("human_not_active")
            status = "CLOSED" if event.kind == "END" else "ACTIVE"
            await session.execute(
                text(
                    "UPDATE public.handoffs SET status=:status,event_sequence=:sequence,"
                    "last_activity_at=greatest(last_activity_at,:activity),closed_at=:closed "
                    "WHERE tenant_id=:tenant AND id=:id"
                ),
                {
                    "status": status,
                    "sequence": event.sequence,
                    "activity": event.occurred_at,
                    "closed": self.now() if status == "CLOSED" else None,
                    "tenant": context.tenant_id,
                    "id": record.id,
                },
            )
            control = self._control(session, context)
            if status == "CLOSED":
                await control.close_conversation(
                    conversation_id=record.conversation_id, reason="human_ended"
                )
            elif record.status == "REQUESTED":
                await control.activate_human(
                    conversation_id=record.conversation_id,
                    reason="verified_human_event",
                )
            await AuditService(session).record(
                context=context,
                event_type="handoff.human_event",
                entity_type="handoff",
                entity_id=record.id,
                payload={
                    "kind": event.kind,
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                },
            )
            return HandoffRecord.model_validate(
                dict(await self._required_record(session, context, record.id))
            )

    async def close_if_inactive(
        self, *, context: TenantContext, handoff_id: UUID
    ) -> bool:
        """Task 35 schedules this; deadline is revalidated under the inbound lock."""
        async with self.transaction(context) as session:
            row = await self._required_record(session, context, handoff_id)
            await self._conversation(
                session, context, row["conversation_id"], lock=True
            )
            row = await self._required_record(session, context, handoff_id)
            record = HandoffRecord.model_validate(dict(row))
            if record.status == "CLOSED":
                return False
            inbound_at = await session.scalar(
                text(
                    "SELECT max(created_at) FROM public.messages WHERE tenant_id=:tenant "
                    "AND conversation_id=:conversation AND direction='inbound' AND sender_type='customer'"
                ),
                {"tenant": context.tenant_id, "conversation": record.conversation_id},
            )
            last = max(record.last_activity_at, inbound_at or record.last_activity_at)
            if self.now() < last + timedelta(
                hours=record.configuration.inactivity_hours
            ):
                return False
            await session.execute(
                text(
                    "UPDATE public.handoffs SET status='CLOSED',closed_at=:now WHERE tenant_id=:tenant AND id=:id"
                ),
                {"now": self.now(), "tenant": context.tenant_id, "id": record.id},
            )
            await self._control(session, context).close_conversation(
                conversation_id=record.conversation_id, reason="handoff_inactivity"
            )
            await AuditService(session).record(
                context=context,
                event_type="handoff.inactivity_closed",
                entity_type="handoff",
                entity_id=record.id,
                payload={"inactivity_hours": record.configuration.inactivity_hours},
            )
            return True

    async def status(
        self, *, context: TenantContext, handoff_id: UUID
    ) -> HandoffRecord:
        async with self.transaction(context) as session:
            return HandoffRecord.model_validate(
                dict(await self._required_record(session, context, handoff_id))
            )

    @staticmethod
    def _control(session: AsyncSession, context: TenantContext) -> ConversationService:
        return ConversationService(
            session=session,
            context=context,
            awaiting_human_policy=AwaitingHumanPolicy.SILENT,
        )

    @staticmethod
    async def _account(
        session: AsyncSession,
        context: TenantContext,
        account_id: UUID,
        *,
        lock: bool = False,
    ) -> RowMapping:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id,status,mode,coexistence_eligibility,health_status,verified_at "
                        "FROM public.whatsapp_accounts WHERE tenant_id=:tenant AND id=:id"
                        + (" FOR UPDATE" if lock else "")
                    ),
                    {"tenant": context.tenant_id, "id": account_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise HandoffError("human_surface_account_unavailable")
        return row

    @staticmethod
    async def _conversation(
        session: AsyncSession,
        context: TenantContext,
        conversation_id: UUID,
        *,
        lock: bool = False,
    ) -> RowMapping:
        # The application role already owns the narrow updated_at permission
        # required by SELECT FOR UPDATE. Keep that existing RLS boundary; do not
        # grant administrators direct conversation-control writes.
        if lock:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id,whatsapp_account_id,control_state FROM public.conversations "
                        "WHERE tenant_id=:tenant AND id=:id"
                        + (" FOR UPDATE" if lock else "")
                    ),
                    {"tenant": context.tenant_id, "id": conversation_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if lock:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
        if row is None:
            raise HandoffError("conversation_unavailable", 404)
        return row

    @staticmethod
    async def _config(
        session: AsyncSession,
        context: TenantContext,
        account_id: UUID,
        *,
        lock: bool = False,
    ) -> RowMapping | None:
        return (
            (
                await session.execute(
                    text(
                        "SELECT * FROM public.handoff_configurations WHERE tenant_id=:tenant AND whatsapp_account_id=:id"
                        + (" FOR SHARE" if lock else "")
                    ),
                    {"tenant": context.tenant_id, "id": account_id},
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    async def _live(
        session: AsyncSession, context: TenantContext, conversation_id: UUID
    ) -> RowMapping | None:
        return (
            (
                await session.execute(
                    text(
                        "SELECT * FROM public.handoffs WHERE tenant_id=:tenant AND conversation_id=:id AND status<>'CLOSED'"
                    ),
                    {"tenant": context.tenant_id, "id": conversation_id},
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    async def _record(
        session: AsyncSession, context: TenantContext, handoff_id: UUID
    ) -> RowMapping | None:
        return (
            (
                await session.execute(
                    text(
                        "SELECT * FROM public.handoffs WHERE tenant_id=:tenant AND id=:id"
                    ),
                    {"tenant": context.tenant_id, "id": handoff_id},
                )
            )
            .mappings()
            .one_or_none()
        )

    async def _required_record(
        self, session: AsyncSession, context: TenantContext, handoff_id: UUID
    ) -> RowMapping:
        row = await self._record(session, context, handoff_id)
        if row is None:
            raise HandoffError("handoff_unavailable", 404)
        return row
