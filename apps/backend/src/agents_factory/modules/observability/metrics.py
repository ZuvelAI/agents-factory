from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.context import TenantContext
from agents_factory.modules.observability.models import EventLinks
from agents_factory.modules.observability.tracing import TraceRecorder


class MetricRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self._recorder = TraceRecorder(session)

    async def record(
        self,
        *,
        context: TenantContext,
        name: str,
        value: float,
        unit: str,
        links: EventLinks = EventLinks(),
        dimensions: Mapping[str, object] | None = None,
    ) -> None:
        await self._recorder.record(
            context=context,
            event_kind="METRIC",
            severity="INFO",
            name=name,
            links=links,
            metric_value=value,
            metric_unit=unit,
            payload=dimensions,
        )
