from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field
from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.modules.usage.models import Currency, Money, UsageModel
from agents_factory.modules.usage.recorder import UsageRecorder


Dimension = Literal["tenant", "run", "conversation", "action", "case", "model", "kind"]


class CostAggregate(UsageModel):
    group: str | None
    currency: Currency
    records: int
    known_cost: Decimal
    unknown_cost_records: int
    input_tokens: Decimal | None
    cached_input_tokens: Decimal | None
    output_tokens: Decimal | None
    reasoning_tokens: Decimal | None
    requests: Decimal | None
    average_latency_ms: Decimal | None
    # Covers only recorded measurements, never an assertion of full producer coverage.
    complete_cost: bool


class MarginEstimate(UsageModel):
    currency: Currency
    revenue: Decimal
    variable_cost: Decimal | None
    gross_profit: Decimal | None
    gross_margin_percent: Decimal | None
    reason: str | None = None


def estimate_margin(revenue: Money, costs: tuple[CostAggregate, ...]) -> MarginEstimate:
    reason = (
        "mixed_currency"
        if any(c.currency != revenue.currency for c in costs)
        else "unknown_cost"
        if any(not c.complete_cost for c in costs)
        else None
    )
    if reason:
        return MarginEstimate(
            currency=revenue.currency,
            revenue=revenue.amount,
            variable_cost=None,
            gross_profit=None,
            gross_margin_percent=None,
            reason=reason,
        )
    cost = sum((c.known_cost for c in costs), Decimal(0))
    profit = revenue.amount - cost
    return MarginEstimate(
        currency=revenue.currency,
        revenue=revenue.amount,
        variable_cost=cost,
        gross_profit=profit,
        gross_margin_percent=None
        if revenue.amount == 0
        else profit * 100 / revenue.amount,
    )


class UsageSummary(UsageModel):
    dimension: Dimension
    groups: tuple[CostAggregate, ...]
    has_more: bool = False
    recorded_data_only: bool = Field(default=True)


async def summarize(
    recorder: UsageRecorder,
    *,
    context: TenantContext,
    start: datetime,
    end: datetime,
    dimension: Dimension = "tenant",
    resolved_only: bool = False,
    limit: int = 100,
) -> UsageSummary:
    columns = {
        "tenant": "tenant_id",
        "run": "run_id",
        "conversation": "conversation_id",
        "action": "action_id",
        "case": "case_id",
        "model": "model",
        "kind": "kind",
    }
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or end <= start
        or (end - start).days > 366
        or not 1 <= limit <= 1000
        or (resolved_only and dimension != "case")
    ):
        raise ValueError("invalid_usage_summary_range")
    column = columns[dimension]
    resolved = (
        "AND EXISTS(SELECT 1 FROM public.cases c WHERE c.tenant_id=u.tenant_id AND c.id=u.case_id AND c.status IN ('RESOLVED','CLOSED'))"
        if resolved_only
        else ""
    )
    async with recorder.transaction(context) as session:
        rows = (
            (
                await session.execute(
                    text(f"""
            SELECT u.{column}::text AS group,u.currency,count(*) AS records,
              coalesce(sum(u.cost_amount),0) AS known_cost,count(*) FILTER(WHERE u.cost_amount IS NULL) AS unknown_cost_records,
              sum((u.event->'measurements'->>'input_tokens')::numeric) AS input_tokens,
              sum((u.event->'measurements'->>'cached_input_tokens')::numeric) AS cached_input_tokens,
              sum((u.event->'measurements'->>'output_tokens')::numeric) AS output_tokens,
              sum((u.event->'measurements'->>'reasoning_tokens')::numeric) AS reasoning_tokens,
              sum((u.event->'measurements'->>'requests')::numeric) AS requests,
              avg((u.event->'measurements'->>'latency_ms')::numeric) AS average_latency_ms
            FROM public.usage_records u WHERE u.tenant_id=:tenant AND u.occurred_at>=:start AND u.occurred_at<:end {resolved}
            GROUP BY u.{column},u.currency ORDER BY u.{column} NULLS FIRST,u.currency LIMIT :limit
        """),
                    {
                        "tenant": context.tenant_id,
                        "start": start,
                        "end": end,
                        "limit": limit + 1,
                    },
                )
            )
            .mappings()
            .all()
        )
    return UsageSummary(
        dimension=dimension,
        groups=tuple(
            CostAggregate(**row, complete_cost=row["unknown_cost_records"] == 0)
            for row in rows[:limit]
        ),
        has_more=len(rows) > limit,
    )
