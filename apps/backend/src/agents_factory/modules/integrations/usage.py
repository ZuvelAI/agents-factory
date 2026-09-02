from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Iterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.modules.usage.models import Measurements, UsageEvent
from agents_factory.modules.usage.recorder import UsageRecorder


@dataclass
class _ExternalRequestScope:
    recorder: UsageRecorder
    session: AsyncSession
    context: TenantContext
    provider: str
    product: str
    execution_id: UUID
    sequence: int = 0

    async def record(self, *, occurrence_known: bool, latency_ms: int) -> None:
        self.sequence += 1
        await self.recorder.record_in_session(
            session=self.session,
            context=self.context,
            event=UsageEvent(
                source_key=f"connector:{self.execution_id}:{self.sequence}",
                occurred_at=datetime.now(UTC),
                kind="tool",
                provider=self.provider,
                product=self.product,
                currency="USD",
                measurements=Measurements(
                    requests=1 if occurrence_known else None,
                    latency_ms=Decimal(latency_ms),
                ),
            ),
        )


_scope: ContextVar[_ExternalRequestScope | None] = ContextVar(
    "external_request_usage_scope", default=None
)


@contextmanager
def external_request_usage(
    *,
    recorder: UsageRecorder,
    session: AsyncSession,
    context: TenantContext,
    provider: str,
    product: str,
    execution_id: UUID,
) -> Iterator[None]:
    reset_handle = _scope.set(
        _ExternalRequestScope(
            recorder=recorder,
            session=session,
            context=context,
            provider=provider,
            product=product,
            execution_id=execution_id,
        )
    )
    try:
        yield
    finally:
        _scope.reset(reset_handle)


async def record_external_request(
    *, provider: str, occurrence_known: bool, latency_ms: int
) -> None:
    scope = _scope.get()
    if scope is None:
        return
    if scope.provider != provider:
        raise RuntimeError("external_usage_provider_mismatch")
    await scope.record(occurrence_known=occurrence_known, latency_ms=latency_ms)
