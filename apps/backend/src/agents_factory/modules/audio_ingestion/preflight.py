"""Wait before attempt accounting, retaining capacity through the handler."""

from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import AsyncIterator, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import JobEnvelope, JobDeferral
from .capacity import AudioCapacityGuard, AudioCapacityLease
from .jobs import load_message_id
from .repository import AudioRepository

current_capacity: ContextVar[AudioCapacityLease | None] = ContextVar(
    "audio_capacity", default=None
)


class AudioJobPreflight:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.factory, self.clock = session_factory, clock
        self.capacity = AudioCapacityGuard(session_factory)

    async def check(self, envelope: JobEnvelope) -> JobDeferral | None:
        if envelope.kind not in {"agent.turn", "whatsapp.audio.transcribe"}:
            return None
        async with self.factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            message = await load_message_id(session, envelope)
            sequence = await session.scalar(
                text(
                    "SELECT arrival_sequence FROM public.messages WHERE tenant_id=:t AND id=:m"
                ),
                {"t": envelope.tenant_id, "m": message},
            )
            context = TenantContext(envelope.tenant_id, None, "system", envelope.job_id)
            until = await AudioRepository(session, context).blocked_until(
                envelope.aggregate_id, sequence, self.clock()
            )
            if until is not None:
                return JobDeferral(
                    min(5.0, max(0.05, (until - self.clock()).total_seconds()))
                )
            if envelope.kind == "whatsapp.audio.transcribe":
                lease = await session.scalar(
                    text(
                        "SELECT lease_expires_at FROM public.whatsapp_audio_transcriptions WHERE tenant_id=:t AND inbound_message_id=:m AND status='PROCESSING'"
                    ),
                    {"t": envelope.tenant_id, "m": message},
                )
                if lease is not None and lease > self.clock():
                    return JobDeferral(5)
        return None

    @asynccontextmanager
    async def admit(self, envelope: JobEnvelope) -> AsyncIterator[JobDeferral | None]:
        deferred = await self.check(envelope)
        if deferred is not None or envelope.kind != "whatsapp.audio.transcribe":
            yield deferred
            return
        async with self.factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            message = await load_message_id(session, envelope)
            needs_capacity = await session.scalar(
                text(
                    "SELECT status IN ('QUEUED','PROCESSING') AND "
                    "CASE WHEN first_claim_at IS NULL THEN created_at+interval '180 seconds'>CAST(:now AS timestamptz) "
                    "ELSE deadline>CAST(:now AS timestamptz) AND (phase='PREFLIGHT' OR lease_expires_at>CAST(:now AS timestamptz)) END "
                    "FROM public.whatsapp_audio_transcriptions WHERE tenant_id=:t AND inbound_message_id=:m"
                ),
                {"t": envelope.tenant_id, "m": message, "now": self.clock()},
            )
        if not needs_capacity:
            yield None
            return
        async with self.capacity.hold(envelope.tenant_id) as permit:
            if permit is None:
                yield JobDeferral(5)
                return
            capacity_context_reset = current_capacity.set(permit)
            try:
                yield None
            finally:
                current_capacity.reset(capacity_context_reset)
