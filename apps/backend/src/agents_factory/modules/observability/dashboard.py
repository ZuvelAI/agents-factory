from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.common.security import PlatformAdmin
from agents_factory.database import set_tenant_context
from agents_factory.dependencies import TransactionSession


DashboardState = Literal["healthy", "attention", "unknown", "empty"]
Freshness = Literal["fresh", "stale", "unknown"]
_TENANT_LIMIT = 100
_USAGE_PERIOD = timedelta(days=30)
_STALE_AFTER = timedelta(hours=24)
_TERMINAL_CASE_STATUSES = (
    "RESOLVED",
    "CLOSED",
    "REJECTED",
    "CANCELLED",
    "EXPIRED",
    "DUPLICATE",
)


class DashboardModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Coverage(DashboardModel):
    tenant_count: int = Field(ge=0)
    included_tenants: int = Field(ge=0)
    complete: bool


class ServiceHealth(DashboardModel):
    name: str
    state: DashboardState


class PlatformOverview(DashboardModel):
    state: DashboardState
    services: tuple[ServiceHealth, ...]


class AgentOverview(DashboardModel):
    configured: int = Field(ge=0)
    operating: int = Field(ge=0)
    state: DashboardState
    freshness: Freshness


class OperationsOverview(DashboardModel):
    work_items_requiring_attention: int = Field(ge=0)
    state: DashboardState
    freshness: Freshness


class CasesOverview(DashboardModel):
    critical_overdue: int = Field(ge=0)
    state: DashboardState
    freshness: Freshness


class IntegrationsOverview(DashboardModel):
    configured: int = Field(ge=0)
    healthy: int = Field(ge=0)
    requiring_attention: int = Field(ge=0)
    unknown: int = Field(ge=0)
    state: DashboardState
    freshness: Freshness
    last_checked_at: datetime | None = None


class CurrencyCost(DashboardModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal = Field(ge=0, decimal_places=12)


class UsageOverview(DashboardModel):
    events: int = Field(ge=0)
    model_tokens: Decimal = Field(ge=0)
    messages: Decimal = Field(ge=0)
    external_requests: Decimal = Field(ge=0)
    tool_calls: Decimal = Field(ge=0)
    known_costs: tuple[CurrencyCost, ...]
    unknown_cost_events: int = Field(ge=0)
    state: DashboardState
    freshness: Freshness
    latest_at: datetime | None = None


class DashboardSummary(DashboardModel):
    generated_at: datetime
    usage_period_start: datetime
    coverage: Coverage
    platform: PlatformOverview
    agents: AgentOverview
    operations: OperationsOverview
    cases: CasesOverview
    integrations: IntegrationsOverview
    usage: UsageOverview


_TENANTS = text(
    "SELECT id,status,count(*) OVER() AS tenant_count "
    "FROM public.tenants ORDER BY created_at,id LIMIT :limit"
)

_TENANT_SNAPSHOT = text(
    "WITH latest_deployments AS ("
    " SELECT DISTINCT ON (agent_instance_id) agent_instance_id"
    " FROM public.agent_spec_deployments WHERE tenant_id=:tenant"
    " ORDER BY agent_instance_id,created_at DESC,id DESC"
    "), integration_health AS ("
    " SELECT status,health_status,last_health_checked_at"
    " FROM public.integration_connections"
    " WHERE tenant_id=:tenant AND status<>'REVOKED'"
    " UNION ALL"
    " SELECT 'CONNECTED',health_status,last_health_checked_at"
    " FROM public.whatsapp_accounts"
    " WHERE tenant_id=:tenant AND status='active'"
    "), usage_window AS ("
    " SELECT * FROM public.usage_records"
    " WHERE tenant_id=:tenant AND occurred_at>=:usage_start"
    "), currency_costs AS ("
    " SELECT currency,sum(cost_amount) AS amount FROM usage_window"
    " WHERE cost_amount IS NOT NULL GROUP BY currency"
    ") SELECT"
    " (SELECT count(*) FROM public.agent_instances"
    "  WHERE tenant_id=:tenant) AS configured_agents,"
    " (SELECT count(*) FROM public.agent_instances AS agent"
    "  WHERE agent.tenant_id=:tenant AND :tenant_active"
    "  AND EXISTS (SELECT 1 FROM latest_deployments AS deployment"
    "              WHERE deployment.agent_instance_id=agent.id)"
    "  AND EXISTS (SELECT 1 FROM public.whatsapp_accounts AS account"
    "              WHERE account.tenant_id=:tenant AND account.status='active'"
    "              AND account.health_status='HEALTHY'"
    "              AND account.last_health_checked_at>=:stale_before))"
    " AS operating_agents,"
    " (SELECT count(*) FROM public.dead_letter_jobs"
    "  WHERE tenant_id=:tenant AND status='open') AS work_items,"
    " (SELECT count(*) FROM public.cases"
    "  WHERE tenant_id=:tenant AND priority='CRITICAL'"
    "  AND status<>ALL(CAST(:terminal_cases AS text[]))"
    "  AND target_at<=:now) AS critical_overdue,"
    " (SELECT count(*) FROM integration_health) AS integrations_configured,"
    " (SELECT count(*) FROM integration_health"
    "  WHERE status='CONNECTED' AND health_status='HEALTHY'"
    "  AND last_health_checked_at>=:stale_before) AS integrations_healthy,"
    " (SELECT count(*) FROM integration_health"
    "  WHERE status IN ('REAUTH_REQUIRED','REVOKING')"
    "  OR health_status IN ('REAUTH_REQUIRED','ERROR'))"
    " AS integrations_attention,"
    " (SELECT count(*) FROM integration_health"
    "  WHERE NOT (status IN ('REAUTH_REQUIRED','REVOKING')"
    "  OR health_status IN ('REAUTH_REQUIRED','ERROR'))"
    "  AND NOT coalesce((status='CONNECTED' AND health_status='HEALTHY'"
    "  AND last_health_checked_at>=:stale_before),false)) AS integrations_unknown,"
    " (SELECT max(last_health_checked_at) FROM integration_health)"
    " AS integrations_last_checked,"
    " (SELECT count(*) FROM usage_window) AS usage_events,"
    " (SELECT coalesce(sum("
    "   coalesce((event#>>'{measurements,input_tokens}')::numeric,0)+"
    "   coalesce((event#>>'{measurements,output_tokens}')::numeric,0)"
    " ),0) FROM usage_window) AS model_tokens,"
    " (SELECT coalesce(sum("
    "   coalesce((event#>>'{measurements,messages}')::numeric,0)"
    " ),0) FROM usage_window) AS messages,"
    " (SELECT coalesce(sum("
    "   coalesce((event#>>'{measurements,requests}')::numeric,0)"
    " ),0) FROM usage_window) AS external_requests,"
    " (SELECT coalesce(sum("
    "   coalesce((event#>>'{measurements,tool_calls}')::numeric,0)"
    " ),0) FROM usage_window) AS tool_calls,"
    " (SELECT count(*) FROM usage_window WHERE cost_amount IS NULL)"
    " AS unknown_cost_events,"
    " (SELECT max(occurred_at) FROM usage_window) AS latest_usage_at,"
    " (SELECT coalesce(jsonb_agg(jsonb_build_object("
    "   'currency',currency,'amount',amount::text) ORDER BY currency),'[]')"
    "  FROM currency_costs) AS known_costs"
)


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summarize(
        self,
        *,
        now: datetime,
        service_checks: Mapping[str, str],
    ) -> DashboardSummary:
        if now.tzinfo is None:
            raise ValueError("dashboard timestamp must be timezone-aware")
        tenant_rows = (
            (await self._session.execute(_TENANTS, {"limit": _TENANT_LIMIT + 1}))
            .mappings()
            .all()
        )
        tenant_count = (
            0 if not tenant_rows else cast(int, tenant_rows[0]["tenant_count"])
        )
        included = tenant_rows[:_TENANT_LIMIT]
        totals = _Totals()
        for tenant in included:
            tenant_id = cast(UUID, tenant["id"])
            await set_tenant_context(self._session, tenant_id)
            snapshot = (
                (
                    await self._session.execute(
                        _TENANT_SNAPSHOT,
                        {
                            "tenant": tenant_id,
                            "tenant_active": tenant["status"] == "active",
                            "now": now,
                            "usage_start": now - _USAGE_PERIOD,
                            "stale_before": now - _STALE_AFTER,
                            "terminal_cases": list(_TERMINAL_CASE_STATUSES),
                        },
                    )
                )
                .mappings()
                .one()
            )
            totals.add(snapshot)

        coverage = Coverage(
            tenant_count=tenant_count,
            included_tenants=len(included),
            complete=tenant_count <= _TENANT_LIMIT,
        )
        return DashboardSummary(
            generated_at=now,
            usage_period_start=now - _USAGE_PERIOD,
            coverage=coverage,
            platform=_platform_overview(service_checks),
            agents=_agent_overview(totals),
            operations=_operations_overview(totals),
            cases=_cases_overview(totals),
            integrations=_integrations_overview(totals, now=now),
            usage=_usage_overview(totals, now=now),
        )


class _Totals:
    def __init__(self) -> None:
        self.configured_agents = 0
        self.operating_agents = 0
        self.work_items = 0
        self.critical_overdue = 0
        self.integrations_configured = 0
        self.integrations_healthy = 0
        self.integrations_attention = 0
        self.integrations_unknown = 0
        self.integrations_last_checked: datetime | None = None
        self.usage_events = 0
        self.model_tokens = Decimal(0)
        self.messages = Decimal(0)
        self.external_requests = Decimal(0)
        self.tool_calls = Decimal(0)
        self.unknown_cost_events = 0
        self.latest_usage_at: datetime | None = None
        self.known_costs: dict[str, Decimal] = {}

    def add(self, row: RowMapping) -> None:
        for name in (
            "configured_agents",
            "operating_agents",
            "work_items",
            "critical_overdue",
            "integrations_configured",
            "integrations_healthy",
            "integrations_attention",
            "integrations_unknown",
            "usage_events",
            "unknown_cost_events",
        ):
            setattr(self, name, getattr(self, name) + int(row[name]))
        for name in ("model_tokens", "messages", "external_requests", "tool_calls"):
            setattr(self, name, getattr(self, name) + Decimal(row[name]))
        self.integrations_last_checked = _latest(
            self.integrations_last_checked,
            cast(datetime | None, row["integrations_last_checked"]),
        )
        self.latest_usage_at = _latest(
            self.latest_usage_at,
            cast(datetime | None, row["latest_usage_at"]),
        )
        costs = row["known_costs"]
        if isinstance(costs, list):
            for cost in costs:
                if not isinstance(cost, dict):
                    continue
                currency, amount = cost.get("currency"), cost.get("amount")
                if isinstance(currency, str) and amount is not None:
                    self.known_costs[currency] = self.known_costs.get(
                        currency, Decimal(0)
                    ) + Decimal(str(amount))


def _latest(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _platform_overview(checks: Mapping[str, str]) -> PlatformOverview:
    services = [ServiceHealth(name="Control API", state="healthy")]
    for key, label in (("database", "Data service"), ("redis", "Work coordination")):
        value = checks.get(key)
        services.append(
            ServiceHealth(
                name=label,
                state=(
                    "healthy"
                    if value == "up"
                    else "attention"
                    if value == "down"
                    else "unknown"
                ),
            )
        )
    state: DashboardState = (
        "attention"
        if any(item.state == "attention" for item in services)
        else "unknown"
        if any(item.state == "unknown" for item in services)
        else "healthy"
    )
    return PlatformOverview(state=state, services=tuple(services))


def _agent_overview(totals: _Totals) -> AgentOverview:
    state: DashboardState = (
        "empty"
        if totals.configured_agents == 0
        else "healthy"
        if totals.operating_agents == totals.configured_agents
        else "attention"
    )
    return AgentOverview(
        configured=totals.configured_agents,
        operating=totals.operating_agents,
        state=state,
        freshness="fresh",
    )


def _operations_overview(totals: _Totals) -> OperationsOverview:
    return OperationsOverview(
        work_items_requiring_attention=totals.work_items,
        state="attention" if totals.work_items else "healthy",
        freshness="fresh",
    )


def _cases_overview(totals: _Totals) -> CasesOverview:
    return CasesOverview(
        critical_overdue=totals.critical_overdue,
        state="attention" if totals.critical_overdue else "healthy",
        freshness="fresh",
    )


def _integrations_overview(totals: _Totals, *, now: datetime) -> IntegrationsOverview:
    state: DashboardState = (
        "empty"
        if totals.integrations_configured == 0
        else "attention"
        if totals.integrations_attention
        else "unknown"
        if totals.integrations_unknown
        else "healthy"
    )
    freshness: Freshness = (
        "unknown"
        if totals.integrations_last_checked is None
        else "stale"
        if totals.integrations_last_checked < now - _STALE_AFTER
        else "fresh"
    )
    return IntegrationsOverview(
        configured=totals.integrations_configured,
        healthy=totals.integrations_healthy,
        requiring_attention=totals.integrations_attention,
        unknown=totals.integrations_unknown,
        state=state,
        freshness=freshness,
        last_checked_at=totals.integrations_last_checked,
    )


def _usage_overview(totals: _Totals, *, now: datetime) -> UsageOverview:
    state: DashboardState = (
        "empty"
        if totals.usage_events == 0
        else "unknown"
        if totals.unknown_cost_events
        else "healthy"
    )
    freshness: Freshness = (
        "unknown"
        if totals.latest_usage_at is None
        else "stale"
        if totals.latest_usage_at < now - _STALE_AFTER
        else "fresh"
    )
    return UsageOverview(
        events=totals.usage_events,
        model_tokens=totals.model_tokens,
        messages=totals.messages,
        external_requests=totals.external_requests,
        tool_calls=totals.tool_calls,
        known_costs=tuple(
            CurrencyCost(currency=currency, amount=amount)
            for currency, amount in sorted(totals.known_costs.items())
        ),
        unknown_cost_events=totals.unknown_cost_events,
        state=state,
        freshness=freshness,
        latest_at=totals.latest_usage_at,
    )


router = APIRouter(prefix="/admin/dashboard", tags=["platform-admin-dashboard"])


async def _readiness(request: Request) -> Mapping[str, str]:
    checks = getattr(request.app.state, "readiness_checks", None)
    if checks is None or not hasattr(checks, "evaluate"):
        return {}
    try:
        result = await checks.evaluate()
    except Exception:
        return {}
    return result if isinstance(result, Mapping) else {}


@router.get("", response_model=DashboardSummary)
async def dashboard(
    request: Request,
    principal: PlatformAdmin,
    session: TransactionSession,
) -> DashboardSummary:
    _ = principal
    now = datetime.now(UTC)
    return await DashboardService(session).summarize(
        now=now,
        service_checks=await _readiness(request),
    )
