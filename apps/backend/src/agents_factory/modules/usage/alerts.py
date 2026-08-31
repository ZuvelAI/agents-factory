from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.audit import AuditService
from agents_factory.common.context import TenantContext
from agents_factory.common.ids import new_uuid7
from agents_factory.modules.usage.guardrails import UsageTotals, commercial_signals
from agents_factory.modules.usage.models import Money, UsageConfiguration, UsageModel


class UsageAlert(UsageModel):
    id: UUID
    period_start: datetime
    period_end: datetime
    configuration_revision: int
    metric: str
    threshold: int
    percentage: Decimal
    state: Literal["alert", "grace_overage"]
    recorded_at: datetime
    recorded_data_only: bool = True


class UsageAlertPage(UsageModel):
    alerts: tuple[UsageAlert, ...]
    has_more: bool


async def persist_alerts(
    session: AsyncSession,
    context: TenantContext,
    config: UsageConfiguration,
    revision: int,
    *,
    concurrent_runs: int | None = None,
) -> None:
    window = config.quota_window
    if window is None:
        return  # Never invent a customer's commercial budget period.
    row = (
        (
            await session.execute(
                text("""
        SELECT CURRENT_TIMESTAMP AS sampled_at,
          CASE WHEN count(*) FILTER(WHERE kind='llm' AND
            (event->'measurements'->>'input_tokens' IS NULL OR
             event->'measurements'->>'output_tokens' IS NULL))=0
          THEN sum((event->'measurements'->>'input_tokens')::numeric +
                   (event->'measurements'->>'output_tokens')::numeric) FILTER(WHERE kind='llm') END AS tokens,
          CASE WHEN count(*) FILTER(WHERE kind='whatsapp' AND event->'measurements'->>'messages' IS NULL)=0
          THEN sum((event->'measurements'->>'messages')::numeric) FILTER(WHERE kind='whatsapp') END AS messages,
          CASE WHEN count(*) FILTER(WHERE kind='tool' AND event->'measurements'->>'tool_calls' IS NULL)=0
          THEN sum((event->'measurements'->>'tool_calls')::numeric) FILTER(WHERE kind='tool') END AS tools,
          nullif(count(DISTINCT conversation_id),0) AS conversations,
          CASE WHEN count(*)>0 AND count(*) FILTER(WHERE cost_amount IS NULL OR currency!=:currency)=0
          THEN sum(cost_amount) END AS cost
        FROM public.usage_records
        WHERE tenant_id=:tenant AND occurred_at>=:start AND occurred_at<:end
    """),
                {
                    "tenant": context.tenant_id,
                    "start": window.start,
                    "end": window.end,
                    "currency": config.commercial.cost.currency
                    if config.commercial.cost
                    else "USD",
                },
            )
        )
        .mappings()
        .one()
    )

    # Missing producers remain unknown. In particular byte-hours are not bytes.
    def integer(name: str) -> int | None:
        return int(row[name]) if row[name] is not None and row[name] <= 10**15 else None

    cost = None
    if row["cost"] is not None and config.commercial.cost:
        try:
            cost = Money(amount=row["cost"], currency=config.commercial.cost.currency)
        except ValueError:
            # Unsupported aggregate magnitude is unknown, not a reason to reject
            # otherwise valid usage or turn a commercial budget into a hard stop.
            pass
    totals = UsageTotals(
        model_tokens=integer("tokens"),
        messages=integer("messages"),
        tool_calls=integer("tools"),
        conversations=integer("conversations"),
        concurrent_runs=concurrent_runs
        if window.start <= row["sampled_at"] < window.end
        else None,
        cost=cost,
    )
    for signal in commercial_signals(config.commercial, totals):
        for threshold in signal.thresholds:
            alert_id = await session.scalar(
                text("""
                INSERT INTO public.usage_alerts
                (id,tenant_id,period_start,period_end,configuration_revision,metric,threshold,percentage,state)
                VALUES (:id,:tenant,:start,:end,:revision,:metric,:threshold,:percentage,:state)
                ON CONFLICT(tenant_id,period_start,period_end,configuration_revision,metric,threshold)
                DO NOTHING RETURNING id
            """),
                {
                    "id": new_uuid7(),
                    "tenant": context.tenant_id,
                    "start": window.start,
                    "end": window.end,
                    "revision": revision,
                    "metric": signal.metric,
                    "threshold": threshold,
                    "percentage": signal.percentage,
                    "state": signal.state,
                },
            )
            if alert_id is not None:
                await AuditService(session).record(
                    context=context,
                    event_type="usage.quota_threshold_crossed",
                    entity_type="usage_alert",
                    entity_id=alert_id,
                    payload={
                        "metric": signal.metric,
                        "threshold": threshold,
                        "state": signal.state,
                        "configuration_revision": revision,
                        "recorded_data_only": True,
                    },
                )


async def list_alerts(
    session: AsyncSession,
    *,
    before: UUID | None = None,
    limit: int = 100,
) -> UsageAlertPage:
    if not 1 <= limit <= 200:
        raise ValueError("invalid_alert_limit")
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,period_start,period_end,configuration_revision,metric,threshold,percentage,state,recorded_at "
                    "FROM public.usage_alerts WHERE (CAST(:before AS uuid) IS NULL OR id < CAST(:before AS uuid)) "
                    "ORDER BY id DESC LIMIT :limit"
                ),
                {"before": before, "limit": limit + 1},
            )
        )
        .mappings()
        .all()
    )
    return UsageAlertPage(
        alerts=tuple(UsageAlert.model_validate(dict(r)) for r in rows[:limit]),
        has_more=len(rows) > limit,
    )
