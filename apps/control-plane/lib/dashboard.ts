export type DashboardState = "healthy" | "attention" | "unknown" | "empty";
export type Freshness = "fresh" | "stale" | "unknown";

export type DashboardSummary = {
  generated_at: string;
  usage_period_start: string;
  coverage: {
    tenant_count: number;
    included_tenants: number;
    complete: boolean;
  };
  platform: {
    state: DashboardState;
    services: { name: string; state: DashboardState }[];
  };
  agents: {
    configured: number;
    operating: number;
    state: DashboardState;
    freshness: Freshness;
  };
  operations: {
    work_items_requiring_attention: number;
    state: DashboardState;
    freshness: Freshness;
  };
  cases: {
    critical_overdue: number;
    state: DashboardState;
    freshness: Freshness;
  };
  integrations: {
    configured: number;
    healthy: number;
    requiring_attention: number;
    unknown: number;
    state: DashboardState;
    freshness: Freshness;
    last_checked_at: string | null;
  };
  usage: {
    events: number;
    model_tokens: string;
    messages: string;
    external_requests: string;
    tool_calls: string;
    known_costs: { currency: string; amount: string }[];
    unknown_cost_events: number;
    state: DashboardState;
    freshness: Freshness;
    latest_at: string | null;
  };
};

export function formatCount(value: number | string): string {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric)
    ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(
        numeric,
      )
    : "Unknown";
}

export function formatCost(amount: string, currency: string): string {
  const numeric = Number(amount);
  if (!Number.isFinite(numeric)) return `${currency} —`;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(numeric);
}

export function formatTime(value: string | null): string {
  if (!value) return "No observation";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(date);
}
