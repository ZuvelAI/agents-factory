import Link from "next/link";

import { DataTable } from "../../../components/data-table";
import { EmptyState } from "../../../components/empty-state";
import { ErrorState } from "../../../components/error-state";
import { StatusBadge } from "../../../components/status";
import { BackendProblem, callAuthenticatedBackend } from "../../../lib/api";
import {
  formatCost,
  formatCount,
  formatTime,
  type DashboardSummary,
  type Freshness,
} from "../../../lib/dashboard";

function FreshnessNote({ freshness }: { freshness: Freshness }) {
  if (freshness === "fresh") return null;
  return (
    <p className="freshness-note">
      {freshness === "stale"
        ? "The latest observation is more than 24 hours old."
        : "There is not enough measured data to determine freshness."}
    </p>
  );
}

function DashboardHeader({ summary }: { summary: DashboardSummary }) {
  return (
    <header className="page-heading dashboard-heading">
      <div>
        <p className="eyebrow">Operations overview</p>
        <h1>Operational dashboard</h1>
        <p>
          Current platform signals and recorded usage across standard tenants.
        </p>
      </div>
      <div className="as-of">
        <span>Updated</span>
        <time dateTime={summary.generated_at}>
          {formatTime(summary.generated_at)} UTC
        </time>
      </div>
    </header>
  );
}

async function loadDashboard(): Promise<DashboardSummary> {
  return callAuthenticatedBackend<DashboardSummary>("/admin/dashboard");
}

export default async function DashboardPage() {
  let summary: DashboardSummary;
  try {
    summary = await loadDashboard();
  } catch (error) {
    return (
      <div className="dashboard-page">
        <header className="page-heading">
          <p className="eyebrow">Operations overview</p>
          <h1>Operational dashboard</h1>
        </header>
        <ErrorState
          correlationId={
            error instanceof BackendProblem ? error.correlationId : undefined
          }
        />
      </div>
    );
  }

  if (summary.coverage.tenant_count === 0) {
    return (
      <div className="dashboard-page">
        <DashboardHeader summary={summary} />
        <EmptyState
          action={{ label: "Create first tenant", href: "/tenants/new" }}
          description="Create a tenant to begin the guided configuration and deployment workflow."
          title="No tenants yet"
        />
      </div>
    );
  }

  const costs = summary.usage.known_costs.map((cost) => [
    cost.currency,
    formatCost(cost.amount, cost.currency),
  ]);

  return (
    <div className="dashboard-page">
      <DashboardHeader summary={summary} />

      {!summary.coverage.complete ? (
        <div className="coverage-warning" role="status">
          Showing {summary.coverage.included_tenants} of{" "}
          {summary.coverage.tenant_count} tenants. Totals are partial.
        </div>
      ) : null}

      <section className="metric-grid" aria-label="Operational status">
        <article className="metric-card">
          <div className="metric-card-heading">
            <p>Agents operating</p>
            <StatusBadge
              href="/agents?status=operating"
              state={summary.agents.state}
            />
          </div>
          <strong className="metric-value">
            {summary.agents.operating}
            <span> / {summary.agents.configured}</span>
          </strong>
          <p>Production agents with an active, recently healthy channel.</p>
          <FreshnessNote freshness={summary.agents.freshness} />
        </article>

        <article className="metric-card">
          <div className="metric-card-heading">
            <p>Operational breakages</p>
            <StatusBadge
              href="/operations?status=needs-attention"
              state={summary.operations.state}
            />
          </div>
          <strong className="metric-value">
            {summary.operations.work_items_requiring_attention}
          </strong>
          <p>Failed work items awaiting an operational decision.</p>
        </article>

        <article className="metric-card">
          <div className="metric-card-heading">
            <p>Critical cases overdue</p>
            <StatusBadge
              href="/cases?priority=CRITICAL&target=overdue"
              state={summary.cases.state}
            />
          </div>
          <strong className="metric-value">
            {summary.cases.critical_overdue}
          </strong>
          <p>Open critical cases beyond their configured response target.</p>
        </article>

        <article className="metric-card">
          <div className="metric-card-heading">
            <p>Integration health</p>
            <StatusBadge
              href="/integrations?health=needs-attention"
              state={summary.integrations.state}
            />
          </div>
          <strong className="metric-value">
            {summary.integrations.healthy}
            <span> / {summary.integrations.configured}</span>
          </strong>
          <p>
            {summary.integrations.requiring_attention} need attention ·{" "}
            {summary.integrations.unknown} unknown
          </p>
          <FreshnessNote freshness={summary.integrations.freshness} />
        </article>
      </section>

      <section className="dashboard-split">
        <article
          className="dashboard-panel"
          aria-labelledby="platform-health-title"
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Platform</p>
              <h2 id="platform-health-title">Service health</h2>
            </div>
            <StatusBadge
              href="/operations?view=services"
              state={summary.platform.state}
            />
          </div>
          <ul className="service-list">
            {summary.platform.services.map((service) => (
              <li key={service.name}>
                <span>{service.name}</span>
                <StatusBadge
                  href={`/operations?service=${encodeURIComponent(service.name)}`}
                  state={service.state}
                />
              </li>
            ))}
          </ul>
          <Link className="text-link" href="/operations">
            View operations
          </Link>
        </article>

        <article className="dashboard-panel" aria-labelledby="usage-title">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Last 30 days</p>
              <h2 id="usage-title">Usage &amp; cost</h2>
            </div>
            <StatusBadge href="/usage?period=30d" state={summary.usage.state} />
          </div>
          <dl className="usage-stats">
            <div>
              <dt>Model tokens</dt>
              <dd>{formatCount(summary.usage.model_tokens)}</dd>
            </div>
            <div>
              <dt>Messages</dt>
              <dd>{formatCount(summary.usage.messages)}</dd>
            </div>
            <div>
              <dt>External requests</dt>
              <dd>{formatCount(summary.usage.external_requests)}</dd>
            </div>
            <div>
              <dt>Tool calls</dt>
              <dd>{formatCount(summary.usage.tool_calls)}</dd>
            </div>
          </dl>
          {costs.length ? (
            <DataTable
              caption="Known recorded cost"
              headers={["Currency", "Cost"]}
              rows={costs}
            />
          ) : (
            <p className="muted-copy">No priced usage has been recorded.</p>
          )}
          {summary.usage.unknown_cost_events ? (
            <p className="freshness-note">
              {summary.usage.unknown_cost_events} usage events have unknown
              cost.
            </p>
          ) : null}
          <FreshnessNote freshness={summary.usage.freshness} />
        </article>
      </section>
    </div>
  );
}
