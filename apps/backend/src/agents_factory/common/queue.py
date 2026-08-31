from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.common.locks import ConversationLockManager
from agents_factory.config import load_settings
from agents_factory.database import Database, set_tenant_context


QueueName = Literal["agent", "knowledge", "outbound", "scheduler"]
JobRunStatus = Literal[
    "succeeded",
    "retry",
    "dead_letter",
    "already_complete",
]
JobHandler = Callable[["JobEnvelope"], Awaitable[None]]


class InvalidJobEnvelope(ValueError):
    pass


class UnsupportedJobKind(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JobEnvelope:
    job_id: UUID
    tenant_id: UUID
    kind: str
    aggregate_id: UUID

    def __post_init__(self) -> None:
        if not self.kind or self.kind != self.kind.strip() or len(self.kind) > 200:
            raise InvalidJobEnvelope("job kind must be a bounded non-empty value")

    def to_arq_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "job_id": str(self.job_id),
            "tenant_id": str(self.tenant_id),
            "kind": self.kind,
            "aggregate_id": str(self.aggregate_id),
        }

    @classmethod
    def from_arq_payload(cls, payload: Mapping[str, object]) -> JobEnvelope:
        if set(payload) != {
            "schema_version",
            "job_id",
            "tenant_id",
            "kind",
            "aggregate_id",
        }:
            raise InvalidJobEnvelope("job envelope fields are invalid")
        if payload["schema_version"] != 1 or not isinstance(payload["kind"], str):
            raise InvalidJobEnvelope("job envelope schema is invalid")
        try:
            return cls(
                job_id=UUID(str(payload["job_id"])),
                tenant_id=UUID(str(payload["tenant_id"])),
                kind=payload["kind"],
                aggregate_id=UUID(str(payload["aggregate_id"])),
            )
        except (TypeError, ValueError):
            raise InvalidJobEnvelope("job envelope identifiers are invalid") from None


def json_job_serializer(value: dict[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise InvalidJobEnvelope("ARQ job is not JSON serializable") from None


def json_job_deserializer(value: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidJobEnvelope("ARQ job is not valid JSON") from None
    if not isinstance(decoded, dict):
        raise InvalidJobEnvelope("ARQ job must be a JSON object")
    return cast(dict[str, Any], decoded)


class ArqQueueClient(Protocol):
    async def enqueue_job(
        self,
        function: str,
        *args: Any,
        _job_id: str | None = None,
        _queue_name: str | None = None,
        **kwargs: Any,
    ) -> object | None: ...


@dataclass(frozen=True, slots=True)
class DispatchBatchResult:
    dispatched: int = 0
    already_enqueued: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class _ClaimedOutboxJob:
    job_id: UUID
    tenant_id: UUID
    kind: str
    payload: dict[str, object]
    lease_id: UUID

    def envelope(self) -> JobEnvelope:
        aggregate_id = self.payload.get("aggregate_id")
        if not isinstance(aggregate_id, str):
            raise InvalidJobEnvelope("outbox payload has no aggregate_id")
        try:
            parsed_aggregate_id = UUID(aggregate_id)
        except ValueError:
            raise InvalidJobEnvelope("outbox aggregate_id is invalid") from None
        return JobEnvelope(
            job_id=self.job_id,
            tenant_id=self.tenant_id,
            kind=self.kind,
            aggregate_id=parsed_aggregate_id,
        )


class OutboxDispatcher:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        queue: ArqQueueClient,
        queue_by_kind: Mapping[str, QueueName],
        lease_seconds: float = 30.0,
        retry_delay_seconds: float = 0.0,
    ) -> None:
        if not queue_by_kind:
            raise ValueError("at least one outbox kind must be registered")
        if not 0 < lease_seconds <= 300:
            raise ValueError("dispatch lease must be between 0 and 300 seconds")
        if retry_delay_seconds < 0:
            raise ValueError("retry delay cannot be negative")
        self._session_factory = session_factory
        self._queue = queue
        self._queue_by_kind = dict(queue_by_kind)
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds

    async def dispatch_once(self, *, limit: int = 100) -> DispatchBatchResult:
        if not 1 <= limit <= 1000:
            raise ValueError("dispatch limit must be between 1 and 1000")
        claimed = await self._claim(limit=limit)
        dispatched = 0
        already_enqueued = 0
        failed = 0
        for job in claimed:
            try:
                envelope = job.envelope()
                if (
                    envelope.kind == "approvals.result.held"
                    and not await self._release_approval_hold(job)
                ):
                    continue
                queued = await self._queue.enqueue_job(
                    "process_job",
                    envelope.to_arq_payload(),
                    _job_id=str(envelope.job_id),
                    _queue_name=self._queue_by_kind[envelope.kind],
                )
            except Exception as error:
                await self._record_dispatch_failure(
                    job=job,
                    error_code=_exception_code(error),
                )
                failed += 1
                continue
            await self._mark_queued(job=job)
            if queued is None:
                already_enqueued += 1
            else:
                dispatched += 1
        return DispatchBatchResult(
            dispatched=dispatched,
            already_enqueued=already_enqueued,
            failed=failed,
        )

    async def _claim(self, *, limit: int) -> list[_ClaimedOutboxJob]:
        now = datetime.now(UTC)
        lease_id = new_uuid7()
        lease_expires_at = now + timedelta(seconds=self._lease_seconds)
        statement = text(
            "WITH candidates AS ("
            "SELECT id FROM public.outbox_jobs "
            "WHERE topic IN :kinds AND ("
            "(status IN ('pending', 'failed') AND available_at <= :now) OR "
            "(status = 'dispatching' AND dispatch_lease_expires_at <= :now)"
            ") ORDER BY available_at, created_at, id "
            "FOR UPDATE SKIP LOCKED LIMIT :limit"
            ") UPDATE public.outbox_jobs AS job "
            "SET status = 'dispatching', dispatch_lease_id = :lease_id, "
            "dispatch_lease_expires_at = :lease_expires_at, updated_at = :now "
            "FROM candidates WHERE job.id = candidates.id "
            "RETURNING job.id, job.tenant_id, job.topic, job.payload"
        ).bindparams(bindparam("kinds", expanding=True))
        async with self._session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            rows = (
                await session.execute(
                    statement,
                    {
                        "kinds": tuple(self._queue_by_kind),
                        "now": now,
                        "limit": limit,
                        "lease_id": lease_id,
                        "lease_expires_at": lease_expires_at,
                    },
                )
            ).mappings()
            return [
                _ClaimedOutboxJob(
                    job_id=row["id"],
                    tenant_id=row["tenant_id"],
                    kind=row["topic"],
                    payload=row["payload"],
                    lease_id=lease_id,
                )
                for row in rows
            ]

    async def _release_approval_hold(self, job: _ClaimedOutboxJob) -> bool:
        # The global dispatcher can read job envelopes, not tenant business rows.
        # Check the conversation in a separate, explicitly tenant-scoped session.
        async with self._session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await set_tenant_context(session, job.tenant_id)
            ready = await session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM public.actions a JOIN public.conversations c ON c.tenant_id=a.tenant_id AND c.id=a.conversation_id WHERE a.tenant_id=:tenant AND a.id=:action AND c.control_state='AI_ACTIVE')"
                ),
                {"tenant": job.tenant_id, "action": job.envelope().aggregate_id},
            )
            if ready:
                return True
            await session.execute(
                text(
                    "UPDATE public.outbox_jobs SET status='pending',dispatch_lease_id=NULL,dispatch_lease_expires_at=NULL,available_at=now()+interval '30 seconds',updated_at=now() WHERE tenant_id=:tenant AND id=:id AND dispatch_lease_id=:lease"
                ),
                {"tenant": job.tenant_id, "id": job.job_id, "lease": job.lease_id},
            )
            return False

    async def _mark_queued(self, *, job: _ClaimedOutboxJob) -> None:
        async with self._session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            updated = await session.scalar(
                text(
                    "UPDATE public.outbox_jobs SET status = 'queued', "
                    "dispatched_at = coalesce(dispatched_at, now()), "
                    "dispatch_lease_id = NULL, dispatch_lease_expires_at = NULL, "
                    "last_error_code = NULL, updated_at = now() "
                    "WHERE id = :job_id AND status = 'dispatching' "
                    "AND dispatch_lease_id = :lease_id RETURNING id"
                ),
                {"job_id": job.job_id, "lease_id": job.lease_id},
            )
        if updated != job.job_id:
            raise RuntimeError("outbox dispatch lease was lost")

    async def _record_dispatch_failure(
        self,
        *,
        job: _ClaimedOutboxJob,
        error_code: str,
    ) -> None:
        available_at = datetime.now(UTC) + timedelta(seconds=self._retry_delay_seconds)
        async with self._session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE agents_factory_admin"))
            await session.execute(
                text(
                    "UPDATE public.outbox_jobs SET status = 'failed', "
                    "available_at = :available_at, last_error_code = :error_code, "
                    "dispatch_lease_id = NULL, dispatch_lease_expires_at = NULL, "
                    "updated_at = now() WHERE id = :job_id "
                    "AND status = 'dispatching' AND dispatch_lease_id = :lease_id"
                ),
                {
                    "job_id": job.job_id,
                    "lease_id": job.lease_id,
                    "available_at": available_at,
                    "error_code": error_code,
                },
            )


@dataclass(frozen=True, slots=True)
class JobRunResult:
    status: JobRunStatus
    attempt_number: int | None


@dataclass(frozen=True, slots=True)
class _StartedAttempt:
    attempt_number: int
    max_attempts: int


class DurableJobRunner:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        conversation_locks: ConversationLockManager | None = None,
        retry_delay_seconds: float = 0.0,
    ) -> None:
        if retry_delay_seconds < 0:
            raise ValueError("retry delay cannot be negative")
        self._session_factory = session_factory
        self._conversation_locks = conversation_locks
        self._retry_delay_seconds = retry_delay_seconds

    async def run(
        self,
        *,
        envelope: JobEnvelope,
        handler: JobHandler,
    ) -> JobRunResult:
        if self._conversation_locks is None:
            return await self._run_attempt(envelope=envelope, handler=handler)
        async with self._conversation_locks.hold(
            tenant_id=envelope.tenant_id,
            conversation_id=envelope.aggregate_id,
        ):
            return await self._run_attempt(envelope=envelope, handler=handler)

    async def _run_attempt(
        self,
        *,
        envelope: JobEnvelope,
        handler: JobHandler,
    ) -> JobRunResult:
        started = await self._start_attempt(envelope=envelope)
        if started is None:
            return JobRunResult(status="already_complete", attempt_number=None)
        try:
            await handler(envelope)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(
                self._finish_failure(
                    envelope=envelope,
                    attempt=started,
                    error_code="cancelled",
                )
            )
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
            raise
        except Exception as error:
            status = await self._finish_failure(
                envelope=envelope,
                attempt=started,
                error_code=_exception_code(error),
            )
            return JobRunResult(
                status=status,
                attempt_number=started.attempt_number,
            )
        await self._finish_success(envelope=envelope, attempt=started)
        return JobRunResult(
            status="succeeded",
            attempt_number=started.attempt_number,
        )

    async def _start_attempt(
        self,
        *,
        envelope: JobEnvelope,
    ) -> _StartedAttempt | None:
        async with self._session_factory.begin() as session:
            context = await _prepare_worker_session(session, envelope)
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT status, topic, payload, attempt_count, max_attempts "
                            "FROM public.outbox_jobs WHERE id = :job_id "
                            "AND tenant_id = :tenant_id FOR UPDATE"
                        ),
                        {
                            "job_id": envelope.job_id,
                            "tenant_id": envelope.tenant_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise InvalidJobEnvelope("job is not visible to its tenant")
            if row["status"] in {"succeeded", "dead_letter"}:
                return None
            if row["status"] not in {"queued", "failed", "dispatching"}:
                raise RuntimeError("job is not ready for execution")
            _validate_ledger_envelope(envelope=envelope, row=row)
            attempt_number = int(row["attempt_count"]) + 1
            max_attempts = int(row["max_attempts"])
            await session.execute(
                text(
                    "UPDATE public.outbox_jobs SET status = 'processing', "
                    "attempt_count = :attempt_number, dispatch_lease_id = NULL, "
                    "dispatch_lease_expires_at = NULL, updated_at = now() "
                    "WHERE id = :job_id AND tenant_id = :tenant_id"
                ),
                {
                    "attempt_number": attempt_number,
                    "job_id": envelope.job_id,
                    "tenant_id": envelope.tenant_id,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO public.job_attempts "
                    "(id, tenant_id, outbox_job_id, attempt_number, status) "
                    "VALUES (:id, :tenant_id, :job_id, :attempt_number, 'started')"
                ),
                {
                    "id": new_uuid7(),
                    "tenant_id": envelope.tenant_id,
                    "job_id": envelope.job_id,
                    "attempt_number": attempt_number,
                },
            )
            _ = context
            return _StartedAttempt(
                attempt_number=attempt_number,
                max_attempts=max_attempts,
            )

    async def _finish_success(
        self,
        *,
        envelope: JobEnvelope,
        attempt: _StartedAttempt,
    ) -> None:
        async with self._session_factory.begin() as session:
            await _prepare_worker_session(session, envelope)
            await session.execute(
                text(
                    "UPDATE public.job_attempts SET status = 'succeeded', "
                    "error_code = NULL WHERE tenant_id = :tenant_id "
                    "AND outbox_job_id = :job_id "
                    "AND attempt_number = :attempt_number"
                ),
                {
                    "tenant_id": envelope.tenant_id,
                    "job_id": envelope.job_id,
                    "attempt_number": attempt.attempt_number,
                },
            )
            updated = await session.scalar(
                text(
                    "UPDATE public.outbox_jobs SET status = 'succeeded', "
                    "last_error_code = NULL, completed_at = now(), "
                    "updated_at = now() WHERE id = :job_id "
                    "AND tenant_id = :tenant_id AND status = 'processing' "
                    "AND attempt_count = :attempt_number RETURNING id"
                ),
                {
                    "tenant_id": envelope.tenant_id,
                    "job_id": envelope.job_id,
                    "attempt_number": attempt.attempt_number,
                },
            )
            if updated != envelope.job_id:
                raise RuntimeError("job completion state changed concurrently")

    async def _finish_failure(
        self,
        *,
        envelope: JobEnvelope,
        attempt: _StartedAttempt,
        error_code: str,
    ) -> Literal["retry", "dead_letter"]:
        terminal = attempt.attempt_number >= attempt.max_attempts
        async with self._session_factory.begin() as session:
            context = await _prepare_worker_session(session, envelope)
            await session.execute(
                text(
                    "UPDATE public.job_attempts SET status = 'failed', "
                    "error_code = :error_code WHERE tenant_id = :tenant_id "
                    "AND outbox_job_id = :job_id "
                    "AND attempt_number = :attempt_number"
                ),
                {
                    "error_code": error_code,
                    "tenant_id": envelope.tenant_id,
                    "job_id": envelope.job_id,
                    "attempt_number": attempt.attempt_number,
                },
            )
            if terminal:
                await session.execute(
                    text(
                        "UPDATE public.outbox_jobs SET status = 'dead_letter', "
                        "last_error_code = :error_code, completed_at = now(), "
                        "updated_at = now() WHERE id = :job_id "
                        "AND tenant_id = :tenant_id AND status = 'processing' "
                        "AND attempt_count = :attempt_number"
                    ),
                    {
                        "error_code": error_code,
                        "tenant_id": envelope.tenant_id,
                        "job_id": envelope.job_id,
                        "attempt_number": attempt.attempt_number,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO public.dead_letter_jobs "
                        "(id, tenant_id, outbox_job_id, reason_code, status) "
                        "VALUES (:id, :tenant_id, :job_id, :reason_code, 'open') "
                        "ON CONFLICT (tenant_id, outbox_job_id) DO NOTHING"
                    ),
                    {
                        "id": new_uuid7(),
                        "tenant_id": envelope.tenant_id,
                        "job_id": envelope.job_id,
                        "reason_code": error_code,
                    },
                )
                await AuditService(session).record(
                    context=context,
                    event_type="job.dead_lettered",
                    entity_type="outbox_job",
                    entity_id=envelope.job_id,
                    payload={
                        "attempt_number": attempt.attempt_number,
                        "reason_code": error_code,
                    },
                )
                return "dead_letter"
            available_at = datetime.now(UTC) + timedelta(
                seconds=self._retry_delay_seconds
            )
            await session.execute(
                text(
                    "UPDATE public.outbox_jobs SET status = 'failed', "
                    "available_at = :available_at, last_error_code = :error_code, "
                    "updated_at = now() WHERE id = :job_id "
                    "AND tenant_id = :tenant_id AND status = 'processing' "
                    "AND attempt_count = :attempt_number"
                ),
                {
                    "available_at": available_at,
                    "error_code": error_code,
                    "tenant_id": envelope.tenant_id,
                    "job_id": envelope.job_id,
                    "attempt_number": attempt.attempt_number,
                },
            )
            return "retry"


async def configure_durable_worker(context: dict[Any, Any]) -> None:
    settings = load_settings()
    database = Database(settings.database_url)
    redis = cast(Redis, context["redis"])
    context["database"] = database
    context["durable_job_runner"] = DurableJobRunner(
        session_factory=database.session_factory,
        conversation_locks=ConversationLockManager(redis),
        retry_delay_seconds=1.0,
    )
    context.setdefault("job_handlers", {})


async def close_durable_worker(context: dict[Any, Any]) -> None:
    database = cast(Database, context["database"])
    await database.dispose()


async def run_registered_job(
    context: dict[Any, Any],
    payload: Mapping[str, object],
) -> JobRunResult:
    envelope = JobEnvelope.from_arq_payload(payload)
    runner = cast(DurableJobRunner, context["durable_job_runner"])
    handlers = cast(Mapping[str, JobHandler], context["job_handlers"])
    handler = handlers.get(envelope.kind)
    if handler is None:

        async def unsupported(_envelope: JobEnvelope) -> None:
            raise UnsupportedJobKind(envelope.kind)

        handler = unsupported
    return await runner.run(envelope=envelope, handler=handler)


async def _prepare_worker_session(
    session: AsyncSession,
    envelope: JobEnvelope,
) -> TenantContext:
    await session.execute(text("SET LOCAL ROLE agents_factory_app"))
    await set_tenant_context(session, envelope.tenant_id)
    return TenantContext(
        tenant_id=envelope.tenant_id,
        actor_id=None,
        actor_type="system",
        correlation_id=new_uuid7(),
    )


def _validate_ledger_envelope(
    *,
    envelope: JobEnvelope,
    row: RowMapping,
) -> None:
    if row["topic"] != envelope.kind:
        raise InvalidJobEnvelope("job kind does not match the durable ledger")
    payload = row["payload"]
    if not isinstance(payload, dict):
        raise InvalidJobEnvelope("durable job payload is invalid")
    aggregate_id = payload.get("aggregate_id")
    if aggregate_id != str(envelope.aggregate_id):
        raise InvalidJobEnvelope("aggregate does not match the durable ledger")


def _exception_code(error: Exception) -> str:
    name = type(error).__name__
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return normalized[:200] or "job_error"
