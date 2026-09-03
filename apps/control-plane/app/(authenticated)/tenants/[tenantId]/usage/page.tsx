import { UsageCostSummary } from "../../../../../components/usage/cost-summary";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import type {
  MarginEstimate,
  UsageDimension,
  UsageFreshness,
  UsageSummary,
} from "../../../../../lib/operations";

const dimensions: UsageDimension[] = [
  "tenant",
  "conversation",
  "case",
  "action",
];

export default async function TenantUsagePage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const { tenantId } = await params;
  const query = await searchParams;
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
      `/admin/tenants/${encodeURIComponent(tenantId)}/usage/summary?${period}&dimension=${dimension}`,
    ),
    callAuthenticatedBackend<UsageFreshness>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/usage/freshness`,
    ),
  ]);
  let margin: MarginEstimate | null = null;
  if (
    query.revenue &&
    /^\d+(?:\.\d+)?$/.test(query.revenue) &&
    query.currency &&
    /^[A-Z]{3}$/.test(query.currency)
  ) {
    const marginParameters = new URLSearchParams(period);
    marginParameters.set("revenue_amount", query.revenue);
    marginParameters.set("currency", query.currency);
    margin = await callAuthenticatedBackend<MarginEstimate>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/usage/margin?${marginParameters}`,
    );
  }
  return (
    <section className="tenant-section usage-page">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Tenant economics</p>
        <h2>Usage &amp; Costs</h2>
        <p>Measured variable costs, attribution and explicit unknowns.</p>
      </header>
      <UsageCostSummary
        freshness={freshness}
        margin={margin}
        queryPrefix={`?tenant=${encodeURIComponent(tenantId)}`}
        summary={summary}
        tenantId={tenantId}
      />
    </section>
  );
}
