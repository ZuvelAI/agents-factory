import "server-only";
import { callAuthenticatedBackend } from "./api";

export type ChannelSummary = {
  account_id: string;
  display_number: string | null;
  connection_status:
    | "unknown"
    | "connected"
    | "disconnected"
    | "review_required";
  checked_at: string | null;
};
export type AgentSummary = {
  id: string;
  tenant_id: string;
  display_name: string;
  published_name: string | null;
  purpose: string | null;
  published_version_id: string | null;
  draft_version_id: string | null;
  has_pending_changes: boolean | null;
  execution_status: "unknown" | "unassigned" | "error" | "paused" | "serving";
  status_checked_at: string | null;
  channel_accounts: ChannelSummary[];
};
export type CompanySummary = {
  id: string;
  name: string;
  agent_count: number;
  agents: AgentSummary[];
};
export type Page<T> = { items: T[]; next_cursor: string | null };
export type FeatureSummary = {
  key: string;
  label: string;
  availability: "available" | "unavailable" | "unknown";
  enabled: boolean;
  reason: string | null;
};
export type AgentConfigurationView = {
  name: string;
  purpose: string | null;
  tone: string | null;
  instructions: string | null;
  model: string | null;
  knowledge_summary: string | null;
  capabilities: FeatureSummary[];
  integrations: FeatureSummary[];
};
export type AgentOverview = {
  summary: AgentSummary;
  published: AgentConfigurationView | null;
  draft: AgentConfigurationView | null;
  unavailable_sections: string[];
};

export const isWorkspaceId = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const record = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const nullableText = (v: unknown) => v === null || typeof v === "string";
const nullableId = (v: unknown) =>
  v === null || (typeof v === "string" && isWorkspaceId(v));
function isAgent(v: unknown): v is AgentSummary {
  return (
    record(v) &&
    typeof v.id === "string" &&
    isWorkspaceId(v.id) &&
    typeof v.tenant_id === "string" &&
    isWorkspaceId(v.tenant_id) &&
    typeof v.display_name === "string" &&
    nullableText(v.published_name) &&
    nullableText(v.purpose) &&
    nullableId(v.published_version_id) &&
    nullableId(v.draft_version_id) &&
    (v.has_pending_changes === null ||
      typeof v.has_pending_changes === "boolean") &&
    ["unknown", "unassigned", "error", "paused", "serving"].includes(
      String(v.execution_status),
    ) &&
    nullableText(v.status_checked_at) &&
    Array.isArray(v.channel_accounts) &&
    v.channel_accounts.every(
      (c) =>
        record(c) &&
        typeof c.account_id === "string" &&
        isWorkspaceId(c.account_id) &&
        nullableText(c.display_number) &&
        nullableText(c.checked_at) &&
        ["unknown", "connected", "disconnected", "review_required"].includes(
          String(c.connection_status),
        ),
    )
  );
}
function parsePage<T>(
  value: unknown,
  check: (item: unknown) => item is T,
): Page<T> {
  if (
    !record(value) ||
    !Array.isArray(value.items) ||
    !value.items.every(check) ||
    !nullableText(value.next_cursor)
  )
    throw new Error("Invalid workspace response");
  return {
    items: value.items,
    next_cursor: value.next_cursor as string | null,
  };
}
function isCompany(v: unknown): v is CompanySummary {
  return (
    record(v) &&
    typeof v.id === "string" &&
    isWorkspaceId(v.id) &&
    typeof v.name === "string" &&
    typeof v.agent_count === "number" &&
    Number.isSafeInteger(v.agent_count) &&
    v.agent_count >= 0 &&
    Array.isArray(v.agents) &&
    v.agents.every((a) => isAgent(a) && a.tenant_id === v.id)
  );
}
export async function readCompanies(
  query?: string,
  cursor?: string,
): Promise<Page<CompanySummary>> {
  const params = new URLSearchParams();
  if (query) params.set("query", query.slice(0, 200));
  if (cursor) params.set("cursor", cursor);
  return parsePage(
    await callAuthenticatedBackend(
      `/admin/agent-workspace/companies${params.size ? `?${params}` : ""}`,
    ),
    isCompany,
  );
}
export async function readAgents(
  tenant: string,
  cursor?: string,
): Promise<Page<AgentSummary> & { company_name: string | null }> {
  if (!isWorkspaceId(tenant)) throw new Error("Invalid company");
  const raw = await callAuthenticatedBackend(
    `/admin/agent-workspace/companies/${tenant}/agents${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  const value = parsePage(raw, isAgent);
  if (value.items.some((a) => a.tenant_id !== tenant))
    throw new Error("Company mismatch");
  return {
    ...value,
    company_name:
      record(raw) && typeof raw.company_name === "string"
        ? raw.company_name
        : null,
  };
}

function isFeature(v: unknown): v is FeatureSummary {
  return (
    record(v) &&
    typeof v.key === "string" &&
    typeof v.label === "string" &&
    ["available", "unavailable", "unknown"].includes(String(v.availability)) &&
    typeof v.enabled === "boolean" &&
    nullableText(v.reason)
  );
}
function isConfiguration(v: unknown): v is AgentConfigurationView {
  return (
    record(v) &&
    typeof v.name === "string" &&
    nullableText(v.purpose) &&
    nullableText(v.tone) &&
    nullableText(v.instructions) &&
    nullableText(v.model) &&
    nullableText(v.knowledge_summary) &&
    Array.isArray(v.capabilities) &&
    v.capabilities.every(isFeature) &&
    Array.isArray(v.integrations) &&
    v.integrations.every(isFeature)
  );
}
export async function readAgent(
  tenant: string,
  agent: string,
): Promise<AgentOverview> {
  if (!isWorkspaceId(tenant) || !isWorkspaceId(agent))
    throw new Error("Invalid agent");
  const value = await callAuthenticatedBackend(
    `/admin/agent-workspace/companies/${tenant}/agents/${agent}`,
  );
  if (
    !record(value) ||
    !isAgent(value.summary) ||
    value.summary.tenant_id !== tenant ||
    value.summary.id !== agent ||
    (value.published !== null && !isConfiguration(value.published)) ||
    (value.draft !== null && !isConfiguration(value.draft)) ||
    !Array.isArray(value.unavailable_sections) ||
    !value.unavailable_sections.every((s) => typeof s === "string")
  )
    throw new Error("Invalid agent response");
  return value as AgentOverview;
}
