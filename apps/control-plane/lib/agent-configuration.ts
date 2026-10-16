import "server-only";
import { callAuthenticatedBackend } from "./api";
import { isWorkspaceId } from "./agent-workspace";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };
export type ConfigurationSection = Record<string, JsonValue>;
export type EditableConfiguration = Record<string, JsonValue> & {
  agent: ConfigurationSection;
  knowledge: ConfigurationSection;
  policies_identity: ConfigurationSection;
  human_operations: ConfigurationSection;
  approval_routes: ConfigurationSection;
  capabilities: ConfigurationSection;
  integrations: ConfigurationSection;
};
export type CompanyProfile = {
  tenant_id: string;
  revision: number;
  configuration: ConfigurationSection;
  updated_at: string;
};
export type Draft = {
  tenant_id: string;
  agent_instance_id: string;
  revision: number;
  company_revision: number;
  current_company_revision: number;
  company_update_available: boolean;
  company_snapshot: ConfigurationSection;
  configuration: EditableConfiguration;
  provenance: ConfigurationSection;
  updated_at: string;
  validation_issues: { field: string; code: string; message: string }[];
};
export type ConfigurationActionState = {
  status: "idle" | "success" | "validation" | "conflict" | "error";
  message?: string;
  submitted?: string;
  draft?: Draft;
  profile?: CompanyProfile;
  href?: string;
};

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
function json(value: unknown, depth = 0): value is JsonValue {
  if (depth > 12) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean")
    return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((item) => json(item, depth + 1));
  return (
    record(value) && Object.values(value).every((item) => json(item, depth + 1))
  );
}
const section = (value: unknown): value is ConfigurationSection =>
  record(value) && json(value);
const revision = (value: unknown): value is number =>
  Number.isSafeInteger(value) && Number(value) > 0;

export function parseProfile(value: unknown): CompanyProfile {
  if (
    !record(value) ||
    typeof value.tenant_id !== "string" ||
    !isWorkspaceId(value.tenant_id) ||
    !revision(value.revision) ||
    !section(value.configuration) ||
    typeof value.updated_at !== "string"
  )
    throw new Error("invalid_profile_contract");
  return value as CompanyProfile;
}
export function parseDraft(value: unknown): Draft {
  if (
    !record(value) ||
    typeof value.tenant_id !== "string" ||
    !isWorkspaceId(value.tenant_id) ||
    typeof value.agent_instance_id !== "string" ||
    !isWorkspaceId(value.agent_instance_id) ||
    !revision(value.revision) ||
    !revision(value.company_revision) ||
    !revision(value.current_company_revision) ||
    typeof value.company_update_available !== "boolean" ||
    !section(value.company_snapshot) ||
    !section(value.provenance) ||
    typeof value.updated_at !== "string" ||
    !record(value.configuration) ||
    !json(value.configuration)
  )
    throw new Error("invalid_draft_contract");
  const config = value.configuration;
  if (
    config.schema_version !== 1 ||
    typeof config.purpose !== "string" ||
    ![
      "agent",
      "knowledge",
      "policies_identity",
      "human_operations",
      "approval_routes",
      "capabilities",
      "integrations",
    ].every((key) => section(config[key]))
  )
    throw new Error("invalid_draft_contract");
  const agent = config.agent as ConfigurationSection;
  if (
    !["gpt-5.6-luna", "gpt-6-luna"].includes(String(agent.model)) ||
    typeof agent.agent_name !== "string" ||
    typeof agent.instructions !== "string"
  )
    throw new Error("invalid_draft_contract");
  if (
    !Array.isArray(value.validation_issues) ||
    !value.validation_issues.every(
      (issue) =>
        record(issue) &&
        [issue.field, issue.code, issue.message].every(
          (item) => typeof item === "string",
        ),
    )
  )
    throw new Error("invalid_draft_contract");
  return value as Draft;
}
export function configurationPath(tenant: string, agent?: string): string {
  if (!isWorkspaceId(tenant) || (agent !== undefined && !isWorkspaceId(agent)))
    throw new Error("invalid_id");
  return `/admin/agent-workspace/companies/${tenant}${agent ? `/agents/${agent}/configuration` : "/profile"}`;
}
export async function readConfiguration(
  tenant: string,
  agent: string,
): Promise<Draft> {
  return parseDraft(
    await callAuthenticatedBackend(configurationPath(tenant, agent)),
  );
}
export async function readProfile(tenant: string): Promise<CompanyProfile> {
  return parseProfile(
    await callAuthenticatedBackend(configurationPath(tenant)),
  );
}
