"""Durable voice preparation. Mutations join the caller's short transaction."""

from datetime import datetime, timedelta
import re
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.outbox import OutboxService
from agents_factory.database import set_tenant_context
from .models import AudioClaim, AudioPhase, AudioTerminalState, AudioTranscript
from .source import load_audio_source


def _aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("audio_clock_requires_timezone")


class AudioRepository:
    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        self.session, self.context = session, context

    async def enqueue(self, message_id: UUID) -> UUID:
        source = await load_audio_source(self.session, self.context, message_id)
        result = await self.session.scalar(
            text(
                "INSERT INTO public.whatsapp_audio_transcriptions "
                "(id,tenant_id,inbound_message_id,conversation_id,whatsapp_account_id,source_event_id,media_id,mime_type,expected_sha256) "
                "VALUES(:id,:tenant,:message,:conversation,:account,:event,:media,:mime,:hash) "
                "ON CONFLICT (tenant_id,inbound_message_id) DO NOTHING RETURNING id"
            ),
            {
                "id": new_uuid7(),
                "tenant": self.context.tenant_id,
                "message": message_id,
                "conversation": source.conversation_id,
                "account": source.account_id,
                "event": source.event_id,
                "media": source.media_id,
                "mime": source.mime_type,
                "hash": source.expected_sha256,
            },
        )
        if result is None:
            result = await self.session.scalar(
                text(
                    "SELECT id FROM public.whatsapp_audio_transcriptions WHERE tenant_id=:t AND inbound_message_id=:m"
                ),
                {"t": self.context.tenant_id, "m": message_id},
            )
        assert isinstance(result, UUID)
        await OutboxService(self.session).enqueue(
            context=self.context,
            idempotency_key=f"whatsapp.audio.transcribe:{message_id}",
            topic="whatsapp.audio.transcribe",
            payload={
                "aggregate_id": str(source.conversation_id),
                "conversation_id": str(source.conversation_id),
                "inbound_message_id": str(message_id),
            },
        )
        return result

    async def claim(
        self, message_id: UUID, owner_id: UUID, now: datetime
    ) -> AudioClaim | None:
        _aware(now)
        await set_tenant_context(self.session, self.context.tenant_id)
        row = (
            (
                await self.session.execute(
                    text(
                        "SELECT * FROM public.whatsapp_audio_transcriptions WHERE tenant_id=:t AND inbound_message_id=:m FOR UPDATE"
                    ),
                    {"t": self.context.tenant_id, "m": message_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["status"] not in {"QUEUED", "PROCESSING"}:
            return None
        if row["status"] == "PROCESSING" and row["lease_expires_at"] > now:
            return None
        if row["phase"] == "PROVIDER_STARTED":
            await self._expire(
                message_id, "UNCERTAIN", "audio_provider_result_uncertain", now
            )
            return None
        first = row["first_claim_at"] or now
        deadline = first + timedelta(seconds=120)
        if (
            row["first_claim_at"] is None
            and now >= row["created_at"] + timedelta(seconds=180)
        ) or now >= deadline:
            await self._expire(message_id, "FAILED", "audio_deadline_exceeded", now)
            return None
        source = await load_audio_source(self.session, self.context, message_id)
        expected = (
            row["whatsapp_account_id"],
            row["conversation_id"],
            row["source_event_id"],
            row["media_id"],
            row["mime_type"],
            row["expected_sha256"],
        )
        if expected != (
            source.account_id,
            source.conversation_id,
            source.event_id,
            source.media_id,
            source.mime_type,
            source.expected_sha256,
        ):
            await self._expire(message_id, "FAILED", "audio_source_changed", now)
            return None
        if row["attempt_count"] >= 100:
            await self._expire(message_id, "FAILED", "audio_attempts_exhausted", now)
            return None
        lease = uuid4()
        expiry = min(deadline, now + timedelta(seconds=45))
        await self.session.execute(
            text(
                "UPDATE public.whatsapp_audio_transcriptions SET status='PROCESSING',lease_id=:lease,owner_id=:owner,"
                "lease_expires_at=:expiry,first_claim_at=:first,deadline=:deadline,attempt_count=attempt_count+1,updated_at=:now "
                "WHERE tenant_id=:t AND inbound_message_id=:m"
            ),
            {
                "lease": lease,
                "owner": owner_id,
                "expiry": expiry,
                "first": first,
                "deadline": deadline,
                "now": now,
                "t": self.context.tenant_id,
                "m": message_id,
            },
        )
        return AudioClaim(
            row["id"],
            source,
            lease,
            owner_id,
            first,
            deadline,
            expiry,
            cast(AudioPhase, row["phase"]),
        )

    async def _expire(
        self, message: UUID, status: AudioTerminalState, error: str, now: datetime
    ) -> None:
        await self.session.execute(
            text(
                "UPDATE public.whatsapp_audio_transcriptions SET status=:status,error_code=:error,lease_id=NULL,"
                "owner_id=NULL,lease_expires_at=NULL,updated_at=:now WHERE tenant_id=:t AND inbound_message_id=:m "
                "AND status IN ('QUEUED','PROCESSING')"
            ),
            {
                "status": status,
                "error": error,
                "now": now,
                "t": self.context.tenant_id,
                "m": message,
            },
        )

    async def start_provider(self, claim: AudioClaim, now: datetime) -> bool:
        _aware(now)
        if claim.source.tenant_id != self.context.tenant_id:
            return False
        await set_tenant_context(self.session, self.context.tenant_id)
        value = await self.session.scalar(
            text(
                "UPDATE public.whatsapp_audio_transcriptions SET phase='PROVIDER_STARTED',lease_expires_at=least(deadline,:expiry),updated_at=:now "
                "WHERE tenant_id=:t AND id=:id AND status='PROCESSING' AND phase='PREFLIGHT' "
                "AND lease_id=:lease AND owner_id=:owner AND lease_expires_at>:now AND deadline>:now RETURNING id"
            ),
            {
                **self._identity(claim),
                "now": now,
                "expiry": now + timedelta(seconds=65),
            },
        )
        return value is not None

    def _identity(self, claim: AudioClaim) -> dict[str, object]:
        return {
            "t": self.context.tenant_id,
            "id": claim.transcription_id,
            "lease": claim.lease_id,
            "owner": claim.owner_id,
        }

    async def renew(self, claim: AudioClaim, now: datetime) -> bool:
        _aware(now)
        if claim.source.tenant_id != self.context.tenant_id:
            return False
        await set_tenant_context(self.session, self.context.tenant_id)
        value = await self.session.scalar(
            text(
                "UPDATE public.whatsapp_audio_transcriptions SET lease_expires_at=least(deadline,:expiry),updated_at=:now "
                "WHERE tenant_id=:t AND id=:id AND status='PROCESSING' AND lease_id=:lease AND owner_id=:owner "
                "AND lease_expires_at>:now AND deadline>:now RETURNING id"
            ),
            {
                **self._identity(claim),
                "now": now,
                "expiry": now + timedelta(seconds=45),
            },
        )
        return value is not None

    async def complete(self, claim: AudioClaim, transcript: AudioTranscript) -> bool:
        if claim.source.tenant_id != self.context.tenant_id:
            return False
        await set_tenant_context(self.session, self.context.tenant_id)
        value = await self.session.scalar(
            text(
                "UPDATE public.whatsapp_audio_transcriptions SET status='READY',transcript=:body,transcript_digest=:hash,"
                "model=:model,usage=:usage,lease_id=NULL,owner_id=NULL,lease_expires_at=NULL,updated_at=now() "
                "WHERE tenant_id=:t AND id=:id AND status='PROCESSING' AND phase='PROVIDER_STARTED' "
                "AND lease_id=:lease AND owner_id=:owner AND lease_expires_at>now() AND deadline>now() RETURNING id"
            ).bindparams(bindparam("usage", type_=JSONB)),
            {
                **self._identity(claim),
                "body": transcript.text,
                "hash": transcript.digest,
                "model": transcript.model,
                "usage": {
                    k: v
                    for k, v in {
                        "input_tokens": transcript.input_tokens,
                        "output_tokens": transcript.output_tokens,
                    }.items()
                    if v is not None
                },
            },
        )
        if value is None:
            return False
        await OutboxService(self.session).enqueue(
            context=self.context,
            idempotency_key=f"agent.turn:{claim.source.message_id}",
            topic="agent.turn",
            payload={
                "aggregate_id": str(claim.source.conversation_id),
                "conversation_id": str(claim.source.conversation_id),
                "inbound_message_id": str(claim.source.message_id),
            },
        )
        return True

    async def finish(
        self, claim: AudioClaim, status: AudioTerminalState, error_code: str
    ) -> bool:
        if (
            status not in {"FAILED", "CANCELLED", "UNCERTAIN"}
            or re.fullmatch(r"[a-z][a-z0-9_]{0,99}", error_code) is None
        ):
            raise ValueError("audio_terminal_result_invalid")
        if claim.source.tenant_id != self.context.tenant_id:
            return False
        await set_tenant_context(self.session, self.context.tenant_id)
        value = await self.session.scalar(
            text(
                "UPDATE public.whatsapp_audio_transcriptions SET status=:status,error_code=:error,lease_id=NULL,owner_id=NULL,"
                "lease_expires_at=NULL,updated_at=now() WHERE tenant_id=:t AND id=:id AND status='PROCESSING' "
                "AND lease_id=:lease AND owner_id=:owner RETURNING id"
            ),
            {**self._identity(claim), "status": status, "error": error_code},
        )
        return value is not None

    async def read_ready(
        self, message_ids: tuple[UUID, ...]
    ) -> dict[UUID, AudioTranscript]:
        if not message_ids:
            return {}
        await set_tenant_context(self.session, self.context.tenant_id)
        rows = (
            await self.session.execute(
                text(
                    "SELECT inbound_message_id,transcript,transcript_digest,model,usage FROM public.whatsapp_audio_transcriptions "
                    "WHERE tenant_id=:t AND status='READY' AND inbound_message_id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"t": self.context.tenant_id, "ids": message_ids},
            )
        ).mappings()
        result = {}
        for row in rows:
            usage = row["usage"] or {}
            transcript = AudioTranscript(
                row["transcript"],
                row["model"],
                usage.get("input_tokens"),
                usage.get("output_tokens"),
            )
            if transcript.digest != row["transcript_digest"]:
                raise ValueError("audio_transcript_integrity_failed")
            result[row["inbound_message_id"]] = transcript
        return result

    async def blocked_until(
        self, conversation_id: UUID, before_sequence: int, now: datetime
    ) -> datetime | None:
        _aware(now)
        await set_tenant_context(self.session, self.context.tenant_id)
        value = await self.session.scalar(
            text(
                "SELECT min(CASE WHEN a.status='QUEUED' THEN a.created_at+interval '180 seconds' ELSE a.deadline END) "
                "FROM public.whatsapp_audio_transcriptions a JOIN public.messages m ON (m.tenant_id,m.id)=(a.tenant_id,a.inbound_message_id) "
                "WHERE a.tenant_id=:t AND a.conversation_id=:c AND m.arrival_sequence<:seq "
                "AND a.status IN ('QUEUED','PROCESSING') AND "
                "(CASE WHEN a.status='QUEUED' THEN a.created_at+interval '180 seconds' ELSE a.deadline END)>:now"
            ),
            {
                "t": self.context.tenant_id,
                "c": conversation_id,
                "seq": before_sequence,
                "now": now,
            },
        )
        return cast(datetime | None, value)
