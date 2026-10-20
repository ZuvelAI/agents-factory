"""Persistence primitives; all callers participate in their existing transaction."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Result, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.database import set_tenant_context
from agents_factory.modules.runtime.contracts import TurnMessage
from agents_factory.modules.whatsapp.contact_identity import meta_contact_identity
from agents_factory.modules.whatsapp.schemas import MetaChangeValue, MetaWebhookPayload

from .models import TrustedLeadContext
from agents_factory.modules.audio_ingestion.repository import AudioRepository


class LeadRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context

    async def execute(
        self,
        sql: str,
        params: Mapping[str, object],
        *,
        json_fields: tuple[str, ...] = (),
    ) -> Result[Any]:
        await set_tenant_context(self.session, self.context.tenant_id)
        statement = text(sql)
        if json_fields:
            statement = statement.bindparams(
                *(bindparam(key, type_=JSONB) for key in json_fields)
            )
        return await self.session.execute(
            statement, {**params, "tenant": self.context.tenant_id}
        )

    async def load_context(
        self,
        *,
        conversation_id: UUID,
        inbound_message_id: UUID,
        agent_instance_id: UUID | None,
        agent_version_id: UUID | None,
    ) -> TrustedLeadContext | None:
        row = (
            (
                await self.execute(
                    "SELECT c.whatsapp_account_id, c.customer_wa_id, e.raw_payload, "
                    "e.whatsapp_message_id, a.waba_id, a.phone_number_id "
                    "FROM public.messages m JOIN public.conversations c ON c.tenant_id=m.tenant_id AND c.id=m.conversation_id "
                    "JOIN public.whatsapp_webhook_events e ON e.tenant_id=m.tenant_id AND e.id=m.source_event_id AND e.whatsapp_account_id=c.whatsapp_account_id AND e.sender_wa_id=c.customer_wa_id "
                    "JOIN public.whatsapp_accounts a ON a.tenant_id=c.tenant_id AND a.id=c.whatsapp_account_id "
                    "WHERE m.tenant_id=:tenant AND m.id=:inbound AND c.id=:conversation "
                    "AND ((CAST(:agent AS uuid) IS NULL AND CAST(:version AS uuid) IS NULL) OR EXISTS(SELECT 1 FROM public.agent_spec_versions v WHERE v.tenant_id=c.tenant_id AND v.agent_instance_id=:agent AND v.id=:version)) "
                    "AND m.direction='inbound' AND m.sender_type='customer'",
                    {
                        "conversation": conversation_id,
                        "inbound": inbound_message_id,
                        "agent": agent_instance_id,
                        "version": agent_version_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        try:
            payload = MetaWebhookPayload.model_validate(row["raw_payload"])
        except ValidationError:
            return None
        matched = []
        for entry in payload.entry:
            if entry.id != row["waba_id"]:
                continue
            for change in entry.changes:
                if (
                    not isinstance(change.value, MetaChangeValue)
                    or change.field != "messages"
                    or change.value.metadata.phone_number_id != row["phone_number_id"]
                ):
                    continue
                for message in change.value.messages:
                    if (
                        message.id == row["whatsapp_message_id"]
                        and message.sender_wa_id == row["customer_wa_id"]
                    ):
                        matched.append(
                            (message, (change.value.model_extra or {}).get("contacts"))
                        )
        if len(matched) != 1:
            return None
        message, contacts = matched[0]
        identity = meta_contact_identity(
            message={
                **message.model_dump(by_alias=True),
                "sender_phone_number": message.sender_phone_number,
                "sender_user_id": message.sender_user_id,
            },
            contacts=contacts,
        )
        # The key type is retained. A numeric user_id never becomes a phone.
        keys = tuple(
            sorted(
                f"{kind}:{value}"
                for kind, value in (
                    ("user", message.sender_user_id),
                    ("phone", identity.phone_number),
                )
                if value
            )
        )
        if not keys:
            return None
        return TrustedLeadContext(
            self.context.tenant_id,
            row["whatsapp_account_id"],
            row["customer_wa_id"],
            conversation_id,
            inbound_message_id,
            agent_instance_id,
            agent_version_id,
            identity.phone_number,
            keys,
            identity.profile_name,
            identity.username,
        )

    async def evidence_messages(
        self, trusted: TrustedLeadContext, message_ids: tuple[UUID, ...]
    ) -> tuple[TurnMessage, ...]:
        await set_tenant_context(self.session, self.context.tenant_id)
        result = await self.session.execute(
            text(
                "SELECT id,message_type,content FROM public.messages WHERE tenant_id=:tenant "
                "AND conversation_id=:conversation AND direction='inbound' AND sender_type='customer' "
                "AND id IN :ids AND arrival_sequence <= (SELECT arrival_sequence FROM public.messages WHERE tenant_id=:tenant AND id=:inbound)"
            ).bindparams(bindparam("ids", expanding=True)),
            {
                "tenant": self.context.tenant_id,
                "conversation": trusted.conversation_id,
                "ids": message_ids,
                "inbound": trusted.inbound_message_id,
            },
        )
        projected = await AudioRepository(self.session, self.context).project_rows(
            [dict(row) for row in result.mappings()]
        )
        return tuple(
            TurnMessage(cast(UUID, row["id"]), "user", row["text"])
            for row in projected
            if isinstance(row["text"], str) and row["text"].strip()
        )

    async def transcription_sources(
        self, trusted: TrustedLeadContext, message_ids: tuple[UUID, ...]
    ) -> list[dict[str, str]]:
        effective = await self.evidence_messages(trusted, message_ids)
        allowed = tuple(message.id for message in effective)
        audio = AudioRepository(self.session, self.context)
        states = await audio.read_states(allowed)
        transcripts = await audio.read_ready(allowed)
        return [
            {
                "message_id": str(identity),
                "source_kind": "AUDIO_TRANSCRIPT",
                "transcription_id": str(states[identity]["transcription_id"]),
                "digest": transcript.digest,
            }
            for identity, transcript in transcripts.items()
        ]

    async def prospect(self, subject_id: UUID) -> RowMapping | None:
        return (
            (
                await self.execute(
                    "SELECT * FROM public.lead_prospects WHERE tenant_id=:tenant AND subject_id=:subject FOR UPDATE",
                    {"subject": subject_id},
                )
            )
            .mappings()
            .one_or_none()
        )

    async def previous_event(self, inbound: UUID) -> RowMapping | None:
        return (
            (
                await self.execute(
                    "SELECT operation,prospect_id FROM public.lead_capture_events WHERE tenant_id=:tenant AND inbound_message_id=:inbound ORDER BY CASE operation WHEN 'SUPPRESS' THEN 0 ELSE 1 END LIMIT 1",
                    {"inbound": inbound},
                )
            )
            .mappings()
            .first()
        )

    async def lock_subject(self, subject_id: UUID) -> bool:
        result = await self.execute(
            "SELECT capture_suppressed FROM public.lead_subjects WHERE tenant_id=:tenant AND id=:subject FOR UPDATE",
            {"subject": subject_id},
        )
        return cast(bool, result.scalar_one())

    async def suppression_source(
        self, subject_ids: tuple[UUID, ...]
    ) -> RowMapping | None:
        result = await self.execute(
            "SELECT suppression_message_id,suppressed_at FROM public.lead_subjects WHERE tenant_id=:tenant AND id=ANY(CAST(:subjects AS uuid[])) AND capture_suppressed ORDER BY suppressed_at,id LIMIT 1",
            {"subjects": list(subject_ids)},
        )
        return result.mappings().one_or_none()

    async def suppress_subject(
        self,
        subject_id: UUID,
        message_id: UUID,
        *,
        suppressed_at: datetime | None = None,
    ) -> None:
        await self.execute(
            "UPDATE public.lead_subjects SET capture_suppressed=true,suppressed_at=coalesce(suppressed_at,:at,now()),suppression_message_id=coalesce(suppression_message_id,:message) WHERE tenant_id=:tenant AND id=:subject",
            {"message": message_id, "subject": subject_id, "at": suppressed_at},
        )
