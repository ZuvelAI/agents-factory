"""Short database transactions around bounded external work; never paid retries."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
import tempfile
from typing import AsyncIterator, Awaitable, Callable, Protocol, TypeVar
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.context import TenantContext
from agents_factory.common.queue import JobEnvelope
from agents_factory.database import set_tenant_context
from .authorization import AudioAuthority
from .capacity import AudioCapacityGuard, AudioCapacityLost, AudioCapacityLease
from .fallback import AudioFallbackService
from .inspection import AudioInspectionError
from .jobs import load_message_id
from .media import AudioDownload, AudioDownloadError
from .models import (
    AudioClaim,
    AudioInspection,
    AudioSource,
    AudioTerminalState,
    AudioTranscript,
)
from .preflight import current_capacity
from .repository import AudioRepository
from .transcriber import AudioTranscriptionError

T = TypeVar("T")


class AudioDownloader(Protocol):
    async def download(
        self, source: AudioSource, destination: Path
    ) -> AudioDownload: ...


class Inspector(Protocol):
    async def inspect(self, path: Path) -> AudioInspection: ...


class Transcriber(Protocol):
    async def transcribe(
        self, path: Path, inspection: AudioInspection
    ) -> AudioTranscript: ...


class AudioIngestionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        downloader: AudioDownloader,
        inspector: Inspector,
        transcriber: Transcriber,
        authority: AudioAuthority,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self.factory, self.downloader, self.inspector, self.transcriber = (
            session_factory,
            downloader,
            inspector,
            transcriber,
        )
        self.authority, self.clock, self.enabled = authority, clock, enabled

    @asynccontextmanager
    async def _repository(
        self, context: TenantContext
    ) -> AsyncIterator[AudioRepository]:
        async with self.factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_app"))
            await set_tenant_context(session, context.tenant_id)
            yield AudioRepository(session, context)

    async def _external(self, work: Awaitable[T], permit: AudioCapacityLease) -> T:
        external = asyncio.ensure_future(work)
        stop = asyncio.Event()

        async def watch_capacity() -> None:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    await permit.check()

        monitor = asyncio.create_task(watch_capacity())
        try:
            done, _ = await asyncio.wait(
                (external, monitor), return_when=asyncio.FIRST_COMPLETED
            )
            if monitor in done:
                await monitor
            result = await external
            stop.set()
            await monitor
            return result
        finally:
            stop.set()
            if not external.done():
                external.cancel()
            # Do not cancel a healthy DB query and inadvertently release its locks.
            await asyncio.gather(external, monitor, return_exceptions=True)

    @asynccontextmanager
    async def _capacity(
        self, envelope: JobEnvelope
    ) -> AsyncIterator[AudioCapacityLease]:
        existing = current_capacity.get()
        if existing is not None:
            yield existing
        else:
            async with AudioCapacityGuard(self.factory).hold(
                envelope.tenant_id
            ) as permit:
                if permit is None:
                    raise RuntimeError("audio_capacity_requires_preflight")
                yield permit

    async def process(self, envelope: JobEnvelope) -> None:
        if envelope.kind != "whatsapp.audio.transcribe":
            raise ValueError("audio_job_kind_invalid")
        context = TenantContext(envelope.tenant_id, None, "system", envelope.job_id)
        async with self._repository(context) as repo:
            message_id = await load_message_id(repo.session, envelope)
        fallback = AudioFallbackService(self.factory, context, self.authority)
        async with self._repository(context) as repo:
            claim = await repo.claim(message_id, uuid4(), self.clock())
        if claim is None:
            async with self._repository(context) as repo:
                error = await repo.session.scalar(
                    text(
                        "SELECT error_code FROM public.whatsapp_audio_transcriptions WHERE tenant_id=:t AND inbound_message_id=:m AND status IN ('FAILED','UNCERTAIN')"
                    ),
                    {"t": context.tenant_id, "m": message_id},
                )
            if error:
                await fallback.finalize(message_id, error)
            return
        async with self._capacity(envelope) as permit:
            provider_started = False
            try:
                async with asyncio.timeout(
                    max(0.01, (claim.deadline - self.clock()).total_seconds())
                ):
                    await permit.check()
                    async with self._repository(context) as repo:
                        authorized = await self.authority.load(
                            repo.session, context, message_id
                        )
                    if authorized is None:
                        await self._finish(
                            context, claim, "CANCELLED", "audio_authority_unavailable"
                        )
                        return
                    if not self.enabled():
                        await self._finish(context, claim, "FAILED", "audio_disabled")
                        await fallback.finalize(message_id, "audio_disabled")
                        return
                    with tempfile.TemporaryDirectory(
                        prefix="aiworkers-voice-"
                    ) as temporary:
                        path = Path(temporary) / "voice.ogg"
                        for attempt in range(2):
                            try:
                                await permit.check()
                                async with self._repository(context) as repo:
                                    if not await repo.begin_download(claim, self.clock()):
                                        raise AudioDownloadError("audio_download_budget_exhausted")
                                downloaded = await self._external(
                                    self.downloader.download(claim.source, path), permit
                                )
                                break
                            except AudioDownloadError as exc:
                                if str(exc) != "audio_download_failed" or attempt == 1:
                                    raise
                        inspection = await self._external(
                            self.inspector.inspect(path), permit
                        )
                        await permit.check()
                        async with self._repository(context) as repo:
                            still_authorized = await self.authority.load(
                                repo.session, context, message_id
                            )
                            if (
                                still_authorized is None
                                or not self.enabled()
                                or still_authorized.id != authorized.id
                                or still_authorized.digest != authorized.digest
                            ):
                                await repo.finish(
                                    claim, "CANCELLED", "audio_authority_changed"
                                )
                                return
                            inspected = await repo.record_inspection(
                                claim, inspection, downloaded.sha256, self.clock()
                            )
                            admitted = inspected and await repo.start_provider(
                                claim, self.clock()
                            )
                            expired = not admitted and await repo.finish(
                                claim, "FAILED", "audio_preflight_lease_expired"
                            )
                        if not admitted:
                            if expired:
                                await fallback.finalize(
                                    message_id, "audio_preflight_lease_expired"
                                )
                            return
                        provider_started = True
                        transcript = await self._external(
                            self.transcriber.transcribe(path, inspection), permit
                        )
                        await permit.check()
                        async with self._repository(context) as repo:
                            expired_result = False
                            if await repo.complete(claim, transcript):
                                from agents_factory.modules.leads.privacy import (
                                    persist_direct_refusal,
                                )

                                await persist_direct_refusal(
                                    repo.session,
                                    context,
                                    conversation_id=claim.source.conversation_id,
                                    inbound_message_id=message_id,
                                    body=transcript.text,
                                )
                            else:
                                expired_result = await repo.finish(
                                    claim,
                                    "UNCERTAIN",
                                    "audio_provider_result_uncertain",
                                )
                        if expired_result:
                            await permit.check()
                            await fallback.finalize(
                                message_id, "audio_provider_result_uncertain"
                            )
            except AudioCapacityLost:
                await self._finish(
                    context,
                    claim,
                    "UNCERTAIN" if provider_started else "FAILED",
                    "audio_capacity_lost",
                )
                return
            except asyncio.CancelledError:
                await asyncio.shield(
                    self._finish(
                        context,
                        claim,
                        "UNCERTAIN" if provider_started else "FAILED",
                        "audio_worker_cancelled",
                    )
                )
                raise
            except (
                AudioDownloadError,
                AudioInspectionError,
                AudioTranscriptionError,
                TimeoutError,
            ) as exc:
                error = (
                    str(exc)
                    if not isinstance(exc, TimeoutError)
                    else "audio_deadline_exceeded"
                )
                status: AudioTerminalState = (
                    "UNCERTAIN"
                    if provider_started and error != "audio_transcription_invalid"
                    else "FAILED"
                )
                if await self._finish(context, claim, status, error):
                    await permit.check()
                    await fallback.finalize(message_id, error)

    async def _finish(
        self,
        context: TenantContext,
        claim: AudioClaim,
        status: AudioTerminalState,
        error: str,
    ) -> bool:
        async with self._repository(context) as repo:
            return await repo.finish(claim, status, error)
