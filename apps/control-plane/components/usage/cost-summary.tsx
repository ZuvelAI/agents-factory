import Link from "next/link";

import { formatCost, formatCount, formatTime } from "../../lib/dashboard";
import type {
  MarginEstimate,
  UsageDimension,
  UsageFreshness,
  UsageSummary,
} from "../../lib/operations";

const dimensions: { value: UsageDimension; label: string }[] = [
  { value: "tenant", label: "Tenant" },
  { value: "conversation", label: "Conversation" },
  { value: "case", label: "Case" },
  { value: "action", label: "Action" },
];

export function UsageCostSummary({
  tenantId,
  summary,
  freshness,
  margin,
  queryPrefix,
}: {
  tenantId: string;
  summary: UsageSummary;
  freshness: UsageFreshness;
  margin: MarginEstimate | null;
  queryPrefix: string;
}) {
  return (
    <div className="usage-workspace">
      <nav aria-label="Cost dimensions" className="conversation-filters">
        {dimensions.map((dimension) => (
          <Link
            aria-current={
              summary.dimension === dimension.value ? "page" : undefined
            }
            href={`${queryPrefix}&dimension=${dimension.value}`}
            key={dimension.value}
          >
            {dimension.label}
          </Link>
        ))}
      </nav>
      <p className="data-freshness">
        <strong>{freshness.state}</strong> · latest recorded event{" "}
        {formatTime(freshness.latest_recorded_at)} · {freshness.records} total
        records. This view contains recorded data only.
      </p>
      {summary.has_more ? (
        <p className="form-notice form-notice-error">
          More groups exist; this page is not a complete cost total.
        </p>
      ) : null}
      <div className="cost-table-wrapper">
        <table className="cost-table">
          <thead>
            <tr>
              <th scope="col">Traceable group</th>
              <th scope="col">Known variable cost</th>
              <th scope="col">Unknown records</th>
              <th scope="col">Tokens</th>
              <th scope="col">Requests</th>
              <th scope="col">Mean latency</th>
            </tr>
          </thead>
          <tbody>
            {summary.groups.map((group, index) => (
              <tr
                key={`${group.group ?? "unattributed"}-${group.currency}-${index}`}
              >
                <td>{groupLink(tenantId, summary.dimension, group.group)}</td>
                <td>
                  {formatCost(group.known_cost, group.currency)}
                  {!group.complete_cost ? " (partial)" : null}
                </td>
                <td>{group.unknown_cost_records}</td>
                <td>
                  {formatCount(
                    Number(group.input_tokens ?? 0) +
                      Number(group.output_tokens ?? 0),
                  )}
                </td>
                <td>{formatCount(group.requests ?? "0")}</td>
                <td>
                  {group.average_latency_ms
                    ? `${formatCount(group.average_latency_ms)} ms`
                    : "Unknown"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {summary.groups.length === 0 ? (
        <p className="empty-state">No recorded usage exists for this period.</p>
      ) : null}
      <section className="margin-panel">
        <div>
          <p className="eyebrow">Manual business comparison</p>
          <h2>Revenue versus variable cost</h2>
          <p>
            Revenue is a manual estimate for this same period and currency. It
            is not a payment or billing workflow.
          </p>
        </div>
        <form className="inline-filter" method="GET">
          <input type="hidden" name="tenant" value={tenantId} />
          <input type="hidden" name="dimension" value={summary.dimension} />
          <label>
            Revenue
            <input min="0" name="revenue" required step="0.01" type="number" />
          </label>
          <label>
            Currency
            <input defaultValue="USD" maxLength={3} name="currency" required />
          </label>
          <button type="submit">Estimate margin</button>
        </form>
        {margin ? (
          <dl className="margin-results">
            <div>
              <dt>Revenue</dt>
              <dd>{formatCost(margin.revenue, margin.currency)}</dd>
            </div>
            <div>
              <dt>Variable cost</dt>
              <dd>
                {margin.variable_cost
                  ? formatCost(margin.variable_cost, margin.currency)
                  : "Unknown"}
              </dd>
            </div>
            <div>
              <dt>Estimated gross margin</dt>
              <dd>
                {margin.gross_margin_percent
                  ? `${Number(margin.gross_margin_percent).toFixed(2)}%`
                  : margin.reason === "mixed_currency"
                    ? "Unknown: mixed currencies"
                    : "Unknown: incomplete cost"}
              </dd>
            </div>
          </dl>
        ) : null}
      </section>
    </div>
  );
}

function groupLink(
  tenantId: string,
  dimension: UsageDimension,
  group: string | null,
) {
  if (!group) return <span>Unattributed</span>;
  if (dimension === "conversation") {
    return (
      <Link href={`/tenants/${tenantId}/conversations?conversation=${group}`}>
        {group}
      </Link>
    );
  }
  if (dimension === "case") {
    return (
      <Link href={`/cases?tenant=${tenantId}&case=${group}`}>{group}</Link>
    );
  }
  return <code>{group}</code>;
}
