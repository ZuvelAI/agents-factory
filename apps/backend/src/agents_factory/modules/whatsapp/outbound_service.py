from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.errors import DomainError
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from agents_factory.modules.whatsapp.contracts import (
    OutboundTemplateRequest,
    OutboundTextRequest,
    ProviderMessageResult,
    WhatsAppDeliveryStatusEvent,
)


OutboundSendStatus = Literal[
    "PREPARED",
    "SENDING",
    "ACCEPTED",
    "SENT",
    "DELIVERED",
    "READ",
    "FAILED",
    "UNCERTAIN",
    "BLOCKED",
]
_FINAL_SEND_STATUSES = frozenset(
    {"ACCEPTED", "SENT", "DELIVERED", "READ", "FAILED", "UNCERTAIN", "BLOCKED"}
)
_SERVICE_WINDOW = timedelta(hours=24)


class OutboundProvider(Protocol):
    async def send_text(
        self,
        request: OutboundTextRequest,
    ) -> ProviderMessageResult: ...

    async def send_template(
        self,
        request: OutboundTemplateRequest,
    ) -> ProviderMessageResult: ...


class ApprovedTemplateRequired(DomainError):
    def __init__(self) -> None:
        super().__init__(
            type="https://agents-factory.dev/problems/approved-template-required",
            title="Approved WhatsApp Template Required",
            status=409,
            detail="An approved WhatsApp template is required for this message.",
            code="approved_template_required",
        )


class OutboundMessageNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class OutboundSendResult:
    message_id: UUID
    status: OutboundSendStatus
    provider_message_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class _ClaimedOutbound:
    message_id: UUID
    kind: Literal["text", "template"]
    whatsapp_account_id: UUID
    phone_number_id: str
    recipient_wa_id: str
    payload: dict[str, object]


class OutboundMessageService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        context: TenantContext,
        provider: OutboundProvider,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._provider = provider

    async def prepare_text(self, *, message_id: UUID) -> UUID:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            await _prepare_app_session(session, self._context.tenant_id)
            existing_id = await session.scalar(
                text(
                    "SELECT id FROM public.outbound_messages "
                    "WHERE tenant_id = :tenant_id "
                    "AND source_message_id = :message_id"
                ),
                {
                    "tenant_id": self._context.tenant_id,
                    "message_id": message_id,
                },
            )
            if isinstance(existing_id, UUID):
                return existing_id
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT message.id, message.conversation_id, "
                            "message.content, conversation.whatsapp_account_id, "
                            "conversation.customer_wa_id, conversation.control_state, "
                            "account.phone_number_id, "
                            "(SELECT max(inbound.provider_timestamp) "
                            " FROM public.messages AS inbound "
                            " WHERE inbound.tenant_id = message.tenant_id "
                            " AND inbound.conversation_id = message.conversation_id "
                            " AND inbound.direction = 'inbound' "
                            " AND inbound.sender_type = 'customer') AS last_inbound_at "
                            "FROM public.messages AS message "
                            "JOIN public.conversations AS conversation "
                            "ON conversation.tenant_id = message.tenant_id "
                            "AND conversation.id = message.conversation_id "
                            "JOIN public.whatsapp_accounts AS account "
                            "ON account.tenant_id = conversation.tenant_id "
                            "AND account.id = conversation.whatsapp_account_id "
                            "WHERE message.tenant_id = :tenant_id "
                            "AND message.id = :message_id "
                            "AND message.direction = 'outbound' "
                            "AND message.sender_type = 'ai' "
                            "AND message.message_type = 'text' "
                            "AND account.status = 'active' FOR UPDATE OF conversation"
                        ),
                        {
                            "tenant_id": self._context.tenant_id,
                            "message_id": message_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise OutboundMessageNotFound(message_id)
            if row["control_state"] != "AI_ACTIVE":
                raise ApprovedTemplateRequired
            last_inbound = row["last_inbound_at"]
            if (
                not isinstance(last_inbound, datetime)
                or now - last_inbound > _SERVICE_WINDOW
            ):
                raise ApprovedTemplateRequired
            content = row["content"]
            body = content.get("text") if isinstance(content, Mapping) else None
            if not isinstance(body, str) or not body.strip():
                raise OutboundMessageNotFound(message_id)

            outbound_id = new_uuid7()
            history = [_history_entry("PREPARED", occurred_at=now)]
            created_id = await session.scalar(
                text(
                    "INSERT INTO public.outbound_messages "
                    "(id, tenant_id, conversation_id, source_message_id, "
                    "whatsapp_account_id, recipient_wa_id, kind, idempotency_key, "
                    "payload, status, status_history) VALUES "
                    "(:id, :tenant_id, :conversation_id, :source_message_id, "
                    ":account_id, :recipient_wa_id, 'text', :idempotency_key, "
                    ":payload, 'PREPARED', :history) "
                    "ON CONFLICT (tenant_id, source_message_id) DO UPDATE "
                    "SET source_message_id = outbound_messages.source_message_id "
                    "RETURNING id"
                ).bindparams(
                    bindparam("payload", type_=JSONB),
                    bindparam("history", type_=JSONB),
                ),
                {
                    "id": outbound_id,
                    "tenant_id": self._context.tenant_id,
                    "conversation_id": row["conversation_id"],
                    "source_message_id": message_id,
                    "account_id": row["whatsapp_account_id"],
                    "recipient_wa_id": row["customer_wa_id"],
                    "idempotency_key": f"outbound.text:{message_id}",
                    "payload": {"body": body},
                    "history": history,
                },
            )
            if not isinstance(created_id, UUID):
                raise RuntimeError("outbound message identity was not returned")
            await OutboxService(session).enqueue(
                context=self._context,
                idempotency_key=f"whatsapp.outbound.send:{created_id}",
                topic="whatsapp.outbound.send",
                payload={
                    "aggregate_id": str(row["conversation_id"]),
                    "message_id": str(created_id),
                },
            )
            await AuditService(session).record(
                context=self._context,
                event_type="whatsapp.outbound.prepared",
                entity_type="outbound_message",
                entity_id=created_id,
                payload={
                    "kind": "text",
                    "conversation_id": str(row["conversation_id"]),
                    "source_message_id": str(message_id),
                },
            )
            return created_id

    async def send(self, message_id: UUID) -> OutboundSendResult:
        claimed, existing = await self._claim(message_id)
        if existing is not None:
            return existing
        if claimed is None:
            raise RuntimeError("outbound claim returned no result")
        try:
            if claimed.kind == "text":
                body = claimed.payload.get("body")
                if not isinstance(body, str):
                    raise ValueError("invalid persisted text payload")
                provider_result = await self._provider.send_text(
                    OutboundTextRequest(
                        context=self._context,
                        whatsapp_account_id=claimed.whatsapp_account_id,
                        phone_number_id=claimed.phone_number_id,
                        recipient_wa_id=claimed.recipient_wa_id,
                        body=body,
                        client_reference=str(claimed.message_id),
                    )
                )
            else:
                template_name = claimed.payload.get("template_name")
                language = claimed.payload.get("language")
                parameters = claimed.payload.get("body_parameters")
                if (
                    not isinstance(template_name, str)
                    or not isinstance(language, str)
                    or not isinstance(parameters, list)
                    or not all(isinstance(value, str) for value in parameters)
                ):
                    raise ValueError("invalid persisted template payload")
                provider_result = await self._provider.send_template(
                    OutboundTemplateRequest(
                        context=self._context,
                        whatsapp_account_id=claimed.whatsapp_account_id,
                        phone_number_id=claimed.phone_number_id,
                        recipient_wa_id=claimed.recipient_wa_id,
                        template_name=template_name,
                        language=language,
                        body_parameters=tuple(cast(list[str], parameters)),
                        client_reference=str(claimed.message_id),
                    )
                )
        except Exception:
            provider_result = ProviderMessageResult(
                outcome="uncertain",
                error_code="provider_exception",
            )
        return await self._complete(message_id, provider_result)

    async def _claim(
        self,
        message_id: UUID,
    ) -> tuple[_ClaimedOutbound | None, OutboundSendResult | None]:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            await _prepare_app_session(session, self._context.tenant_id)
            row = await _load_outbound_for_update(
                session,
                tenant_id=self._context.tenant_id,
                message_id=message_id,
            )
            if row is None:
                raise OutboundMessageNotFound(message_id)
            status = cast(OutboundSendStatus, row["status"])
            if status in _FINAL_SEND_STATUSES:
                return None, _result_from_row(row)
            if status == "SENDING":
                updated = await _set_status(
                    session,
                    tenant_id=self._context.tenant_id,
                    message_id=message_id,
                    current_history=row["status_history"],
                    status="UNCERTAIN",
                    occurred_at=now,
                    error_code="send_outcome_unknown",
                )
                return None, updated
            if status != "PREPARED":
                raise RuntimeError("outbound message has an invalid send state")

            if row["account_status"] != "active":
                blocked = await _set_status(
                    session,
                    tenant_id=self._context.tenant_id,
                    message_id=message_id,
                    current_history=row["status_history"],
                    status="BLOCKED",
                    occurred_at=now,
                    error_code="whatsapp_account_inactive",
                )
                return None, blocked

            conversation_id = row["conversation_id"]
            if isinstance(conversation_id, UUID):
                authority = (
                    (
                        await session.execute(
                            text(
                                "SELECT control_state, "
                                "(SELECT max(message.provider_timestamp) "
                                " FROM public.messages AS message "
                                " WHERE message.tenant_id = conversation.tenant_id "
                                " AND message.conversation_id = conversation.id "
                                " AND message.direction = 'inbound' "
                                " AND message.sender_type = 'customer') "
                                "AS last_inbound_at "
                                "FROM public.conversations AS conversation "
                                "WHERE conversation.tenant_id = :tenant_id "
                                "AND conversation.id = :conversation_id FOR UPDATE"
                            ),
                            {
                                "tenant_id": self._context.tenant_id,
                                "conversation_id": conversation_id,
                            },
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                authority_available = authority is not None
                if authority is not None:
                    authority_available = authority["control_state"] == "AI_ACTIVE"
                if (
                    authority is not None
                    and row["kind"] == "text"
                    and authority_available
                ):
                    last_inbound = authority["last_inbound_at"]
                    authority_available = (
                        isinstance(last_inbound, datetime)
                        and now - last_inbound <= _SERVICE_WINDOW
                    )
                if not authority_available:
                    blocked = await _set_status(
                        session,
                        tenant_id=self._context.tenant_id,
                        message_id=message_id,
                        current_history=row["status_history"],
                        status="BLOCKED",
                        occurred_at=now,
                        error_code="conversation_authority_unavailable",
                    )
                    return None, blocked

            history = _append_history(
                row["status_history"],
                _history_entry("SENDING", occurred_at=now),
            )
            await session.execute(
                text(
                    "UPDATE public.outbound_messages SET status = 'SENDING', "
                    "attempt_count = attempt_count + 1, last_attempt_at = :now, "
                    "status_history = :history, updated_at = :now "
                    "WHERE tenant_id = :tenant_id AND id = :message_id"
                ).bindparams(bindparam("history", type_=JSONB)),
                {
                    "tenant_id": self._context.tenant_id,
                    "message_id": message_id,
                    "history": history,
                    "now": now,
                },
            )
            kind = row["kind"]
            if kind not in {"text", "template"}:
                raise RuntimeError("outbound kind is invalid")
            return (
                _ClaimedOutbound(
                    message_id=message_id,
                    kind=cast(Literal["text", "template"], kind),
                    whatsapp_account_id=cast(UUID, row["whatsapp_account_id"]),
                    phone_number_id=cast(str, row["phone_number_id"]),
                    recipient_wa_id=cast(str, row["recipient_wa_id"]),
                    payload=cast(dict[str, object], row["payload"]),
                ),
                None,
            )

    async def _complete(
        self,
        message_id: UUID,
        provider_result: ProviderMessageResult,
    ) -> OutboundSendResult:
        now = datetime.now(UTC)
        status = cast(
            OutboundSendStatus,
            {
                "accepted": "ACCEPTED",
                "rejected": "FAILED",
                "uncertain": "UNCERTAIN",
            }[provider_result.outcome],
        )
        async with self._session_factory.begin() as session:
            await _prepare_app_session(session, self._context.tenant_id)
            row = await _load_outbound_for_update(
                session,
                tenant_id=self._context.tenant_id,
                message_id=message_id,
            )
            if row is None:
                raise OutboundMessageNotFound(message_id)
            if row["status"] != "SENDING":
                return _result_from_row(row)
            result = await _set_status(
                session,
                tenant_id=self._context.tenant_id,
                message_id=message_id,
                current_history=row["status_history"],
                status=status,
                occurred_at=now,
                provider_message_id=provider_result.provider_message_id,
                error_code=provider_result.error_code,
            )
            await AuditService(session).record(
                context=self._context,
                event_type="whatsapp.outbound.send_completed",
                entity_type="outbound_message",
                entity_id=message_id,
                payload={
                    "status": status,
                    "provider_message_id_present": (
                        provider_result.provider_message_id is not None
                    ),
                    "error_code": provider_result.error_code,
                },
            )
            return result


class OutboundStatusReconciler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reconcile(
        self,
        *,
        context: TenantContext,
        whatsapp_account_id: UUID,
        event: WhatsAppDeliveryStatusEvent,
    ) -> bool:
        await set_tenant_context(self._session, context.tenant_id)
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, status, status_history, cost_attribution, "
                        "provider_error_code FROM public.outbound_messages "
                        "WHERE tenant_id = :tenant_id "
                        "AND whatsapp_account_id = :account_id "
                        "AND provider_message_id = :provider_message_id "
                        "AND recipient_wa_id = :recipient_wa_id FOR UPDATE"
                    ),
                    {
                        "tenant_id": context.tenant_id,
                        "account_id": whatsapp_account_id,
                        "provider_message_id": event.whatsapp_message_id,
                        "recipient_wa_id": event.recipient_wa_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return False
        callback_status = cast(
            OutboundSendStatus,
            {
                "sent": "SENT",
                "delivered": "DELIVERED",
                "read": "READ",
                "failed": "FAILED",
                "deleted": "FAILED",
            }[event.status],
        )
        current_status = cast(OutboundSendStatus, row["status"])
        next_status = _reconciled_current_status(current_status, callback_status)
        entry = _history_entry(
            callback_status,
            occurred_at=event.occurred_at,
            source="provider_callback",
            error_code=event.error_code,
        )
        history = _append_history(row["status_history"], entry, deduplicate=True)
        cost = (
            event.cost_attribution
            if event.cost_attribution
            else cast(dict[str, object], row["cost_attribution"])
        )
        error_code = event.error_code or cast(str | None, row["provider_error_code"])
        await self._session.execute(
            text(
                "UPDATE public.outbound_messages SET status = :status, "
                "status_history = :history, cost_attribution = :cost, "
                "provider_error_code = :error_code, "
                "delivered_at = CASE WHEN :callback_status = 'DELIVERED' "
                "THEN coalesce(delivered_at, :occurred_at) ELSE delivered_at END, "
                "read_at = CASE WHEN :callback_status = 'READ' "
                "THEN coalesce(read_at, :occurred_at) ELSE read_at END, "
                "failed_at = CASE WHEN :callback_status = 'FAILED' "
                "THEN coalesce(failed_at, :occurred_at) ELSE failed_at END, "
                "updated_at = now() WHERE tenant_id = :tenant_id AND id = :id"
            ).bindparams(
                bindparam("history", type_=JSONB),
                bindparam("cost", type_=JSONB),
            ),
            {
                "status": next_status,
                "callback_status": callback_status,
                "history": history,
                "cost": cost,
                "error_code": error_code,
                "occurred_at": event.occurred_at,
                "tenant_id": context.tenant_id,
                "id": row["id"],
            },
        )
        await AuditService(self._session).record(
            context=context,
            event_type="whatsapp.outbound.status_reconciled",
            entity_type="outbound_message",
            entity_id=cast(UUID, row["id"]),
            payload={
                "callback_status": callback_status,
                "current_status": next_status,
                "cost_attribution_present": bool(event.cost_attribution),
                "error_code": event.error_code,
            },
        )
        return True


async def _prepare_app_session(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(text("SET LOCAL ROLE agents_factory_app"))
    await set_tenant_context(session, tenant_id)


async def _load_outbound_for_update(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    message_id: UUID,
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    "SELECT outbound.id, outbound.conversation_id, outbound.kind, "
                    "outbound.whatsapp_account_id, outbound.recipient_wa_id, "
                    "outbound.payload, outbound.status, outbound.status_history, "
                    "outbound.provider_message_id, outbound.provider_error_code, "
                    "account.phone_number_id, account.status AS account_status "
                    "FROM public.outbound_messages AS outbound "
                    "JOIN public.whatsapp_accounts AS account "
                    "ON account.tenant_id = outbound.tenant_id "
                    "AND account.id = outbound.whatsapp_account_id "
                    "WHERE outbound.tenant_id = :tenant_id "
                    "AND outbound.id = :message_id FOR UPDATE OF outbound"
                ),
                {"tenant_id": tenant_id, "message_id": message_id},
            )
        )
        .mappings()
        .one_or_none()
    )


async def _set_status(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    message_id: UUID,
    current_history: object,
    status: OutboundSendStatus,
    occurred_at: datetime,
    provider_message_id: str | None = None,
    error_code: str | None = None,
) -> OutboundSendResult:
    history = _append_history(
        current_history,
        _history_entry(status, occurred_at=occurred_at, error_code=error_code),
    )
    row = (
        (
            await session.execute(
                text(
                    "UPDATE public.outbound_messages SET status = :status, "
                    "provider_message_id = coalesce(:provider_message_id, "
                    "provider_message_id), provider_error_code = :error_code, "
                    "status_history = :history, "
                    "accepted_at = CASE WHEN :status = 'ACCEPTED' "
                    "THEN coalesce(accepted_at, :occurred_at) ELSE accepted_at END, "
                    "failed_at = CASE WHEN :status = 'FAILED' "
                    "THEN coalesce(failed_at, :occurred_at) ELSE failed_at END, "
                    "updated_at = :occurred_at "
                    "WHERE tenant_id = :tenant_id AND id = :message_id "
                    "RETURNING id, status, provider_message_id, provider_error_code"
                ).bindparams(bindparam("history", type_=JSONB)),
                {
                    "status": status,
                    "provider_message_id": provider_message_id,
                    "error_code": error_code,
                    "history": history,
                    "occurred_at": occurred_at,
                    "tenant_id": tenant_id,
                    "message_id": message_id,
                },
            )
        )
        .mappings()
        .one()
    )
    return _result_from_row(row)


def _result_from_row(row: RowMapping) -> OutboundSendResult:
    return OutboundSendResult(
        message_id=cast(UUID, row["id"]),
        status=cast(OutboundSendStatus, row["status"]),
        provider_message_id=cast(str | None, row["provider_message_id"]),
        error_code=cast(str | None, row["provider_error_code"]),
    )


def _history_entry(
    status: OutboundSendStatus,
    *,
    occurred_at: datetime,
    source: str = "outbound_service",
    error_code: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "status": status,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "source": source,
    }
    if error_code is not None:
        entry["error_code"] = error_code
    return entry


def _append_history(
    value: object,
    entry: dict[str, object],
    *,
    deduplicate: bool = False,
) -> list[dict[str, object]]:
    history = (
        [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, list)
        else []
    )
    if not deduplicate or entry not in history:
        history.append(entry)
    return history


def _reconciled_current_status(
    current: OutboundSendStatus,
    callback: OutboundSendStatus,
) -> OutboundSendStatus:
    if current == "READ":
        return current
    if callback == "FAILED" and current in {"DELIVERED", "READ"}:
        return current
    rank = {"ACCEPTED": 1, "SENT": 2, "DELIVERED": 3, "READ": 4}
    if callback == "FAILED":
        return callback
    if rank.get(callback, 0) >= rank.get(current, 0):
        return callback
    return current
