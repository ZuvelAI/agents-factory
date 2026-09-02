import { UsageCostSummary } from "../../../components/usage/cost-summary";
import { callAuthenticatedBackend } from "../../../lib/api";
import type {
  MarginEstimate,
  UsageDimension,
  UsageFreshness,
  UsageSummary,
} from "../../../lib/operations";
import type { Tenant } from "../../../lib/tenant";

const dimensions: UsageDimension[] = [
  "tenant",
  "conversation",
  "case",
  "action",
];

export default async function UsagePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const query = await searchParams;
  const tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  const tenant =
    tenants.find((item) => item.id === query.tenant) ?? tenants.at(0) ?? null;
  if (!tenant) {
    return (
      <p className="empty-state">Create a tenant before reviewing usage.</p>
    );
  }
  const dimension =
    dimensions.find((item) => item === query.dimension) ?? "tenant";
  const end = new Date();
  const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
  const period = new URLSearchParams({
    start: start.toISOString(),
    end: end.toISOString(),
  });
  const [summary, freshness] = await Promise.all([
    callAuthenticatedBackend<UsageSummary>(
      `/admin/tenants/${encodeURIComponent(tenant.id)}/usage/summary?${period}&dimension=${dimension}`,
    ),
    callAuthenticatedBackend<UsageFreshness>(
      `/admin/tenants/${encodeURIComponent(tenant.id)}/usage/freshness`,
    ),
  ]);
  const margin = await loadMargin(tenant.id, period, query);

  return (
    <section className="narrow-page usage-page">
      <header className="page-heading">
        <p className="eyebrow">Recorded-data-only economics</p>
        <h1>Usage &amp; Costs</h1>
        <p>
          Trace measured variable cost without inventing missing prices,
          infrastructure allocations or currency conversion.
        </p>
      </header>
      <form className="operational-filters" method="GET">
        <label>
          Tenant
          <select defaultValue={tenant.id} name="tenant">
            {tenants.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <input type="hidden" name="dimension" value={dimension} />
        <button type="submit">Load tenant costs</button>
      </form>
      <UsageCostSummary
        freshness={freshness}
        margin={margin}
        queryPrefix={`?tenant=${encodeURIComponent(tenant.id)}`}
        summary={summary}
        tenantId={tenant.id}
      />
    </section>
  );
}

async function loadMargin(
  tenantId: string,
  period: URLSearchParams,
  query: Record<string, string | undefined>,
): Promise<MarginEstimate | null> {
  if (
    !query.revenue ||
    !/^\d+(?:\.\d+)?$/.test(query.revenue) ||
    !query.currency ||
    !/^[A-Z]{3}$/.test(query.currency)
  ) {
    return null;
  }
  const parameters = new URLSearchParams(period);
  parameters.set("revenue_amount", query.revenue);
  parameters.set("currency", query.currency);
  return callAuthenticatedBackend<MarginEstimate>(
    `/admin/tenants/${encodeURIComponent(tenantId)}/usage/margin?${parameters}`,
  );
}
