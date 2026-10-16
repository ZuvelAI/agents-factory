import "server-only";
import { callAuthenticatedBackend } from "./api";
import { isWorkspaceId } from "./agent-workspace";

export type PublicationVersion = {
  id: string;
  tenant_id: string;
  agent_instance_id: string;
  version_number: number;
  state: string;
  compiled_digest: string;
  model: string;
  instructions: string;
  business_name: string;
};
export type Candidate = {
  version: PublicationVersion;
  revision: number;
  company_revision: number;
};
export type Scenario = {
  key: string;
  prompt: string;
  response: string | null;
  passed: boolean;
  error_code: string | null;
};
export type PreviewMessage = { role: "user" | "assistant"; text: string };
export type Run = {
  id: string;
  version_id: string;
  agent_instance_id: string;
  draft_revision: number;
  run_kind: "SCENARIOS" | "PREVIEW";
  is_current: boolean;
  approved: boolean | null;
  expires_at: string;
  input_messages: PreviewMessage[] | null;
  result:
    | null
    | { checks_passed: boolean; scenarios: Scenario[] }
    | { response: string | null; error_code: string | null };
};
export type Binding = {
  tenant_id: string;
  agent_instance_id: string;
  version_id: string;
  whatsapp_account_id: string;
  revision: number;
};
export type PublicationAccount = {
  id: string;
  display_phone_number: string | null;
  status: string;
  health_status: string;
  binding: Binding | null;
  current_version: PublicationVersion | null;
};
export type PublicationState = {
  draft_revision: number;
  company_revision: number;
  blockers: string[];
  candidates: Candidate[];
  runs: Run[];
  accounts: PublicationAccount[];
  versions: PublicationVersion[];
  bindings: Binding[];
  rollback_targets: string[];
  next_cursor: string | null;
  section: string;
};
export type PublicationActionState = {
  status: "idle" | "success" | "conflict" | "error" | "validation";
  message?: string;
  state?: PublicationState;
  run?: Run;
};
const record = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const id = (v: unknown): v is string =>
  typeof v === "string" && isWorkspaceId(v);
const count = (v: unknown, min = 1): v is number =>
  Number.isSafeInteger(v) && Number(v) >= min;
const text = (v: unknown): v is string => typeof v === "string";
const nullableText = (v: unknown): v is string | null => v === null || text(v);
const digest = (v: unknown): v is string => text(v) && /^[0-9a-f]{64}$/.test(v);
function invalid(): never {
  throw new Error("invalid_publication_contract");
}
export function publicationPath(tenant: string, agent: string): string {
  if (!id(tenant) || !id(agent)) return invalid();
  return `/admin/agent-workspace/companies/${tenant}/agents/${agent}/publication`;
}
function parseVersion(v: unknown): PublicationVersion {
  if (
    !record(v) ||
    !id(v.id) ||
    !id(v.tenant_id) ||
    !id(v.agent_instance_id) ||
    !count(v.version_number) ||
    !text(v.state) ||
    !["TEST", "QUALITY_GATE", "PRODUCTION"].includes(v.state) ||
    !digest(v.compiled_digest) ||
    !record(v.configuration) ||
    !record(v.configuration.model) ||
    !["gpt-5.6-luna", "gpt-6-luna"].includes(
      String(v.configuration.model.model),
    ) ||
    !record(v.configuration.persona) ||
    !text(v.configuration.persona.instructions) ||
    !text(v.configuration.persona.business_name)
  )
    return invalid();
  return {
    id: v.id,
    tenant_id: v.tenant_id,
    agent_instance_id: v.agent_instance_id,
    version_number: v.version_number,
    state: v.state,
    compiled_digest: v.compiled_digest,
    model: String(v.configuration.model.model),
    instructions: v.configuration.persona.instructions,
    business_name: v.configuration.persona.business_name,
  };
}
export function parsePublicationRun(v: unknown): Run {
  if (
    !record(v) ||
    !id(v.id) ||
    !id(v.version_id) ||
    !id(v.agent_instance_id) ||
    !count(v.draft_revision) ||
    v.source_kind !== "AGENT_CONFIGURATION" ||
    !["SCENARIOS", "PREVIEW"].includes(String(v.run_kind)) ||
    typeof v.is_current !== "boolean" ||
    !(v.approved === null || typeof v.approved === "boolean") ||
    !text(v.expires_at) ||
    !Number.isFinite(Date.parse(v.expires_at))
  )
    return invalid();
  if (
    v.run_kind === "PREVIEW" &&
    (!Array.isArray(v.input_messages) ||
      !v.input_messages.every(
        (m) =>
          record(m) &&
          ["user", "assistant"].includes(String(m.role)) &&
          text(m.text),
      ))
  )
    return invalid();
  if (v.run_kind === "SCENARIOS" && v.input_messages !== null) return invalid();
  if (v.result !== null) {
    if (!record(v.result)) return invalid();
    if (v.run_kind === "PREVIEW") {
      if (
        !nullableText(v.result.response) ||
        !nullableText(v.result.error_code) ||
        (v.result.response === null) === (v.result.error_code === null) ||
        v.approved !== null
      )
        return invalid();
    } else {
      if (
        typeof v.result.checks_passed !== "boolean" ||
        !Array.isArray(v.result.scenarios) ||
        !v.result.scenarios.every(
          (s) =>
            record(s) &&
            text(s.key) &&
            text(s.prompt) &&
            nullableText(s.response) &&
            typeof s.passed === "boolean" &&
            nullableText(s.error_code),
        )
      )
        return invalid();
      if (
        v.result.checks_passed &&
        (v.result.scenarios.length !== 6 ||
          new Set(v.result.scenarios.map((s) => s.key)).size !== 6 ||
          v.result.scenarios.some((s) => !s.passed || s.error_code !== null))
      )
        return invalid();
    }
  }
  return v as Run;
}
function parseBinding(v: unknown): Binding {
  if (
    !record(v) ||
    !id(v.tenant_id) ||
    !id(v.agent_instance_id) ||
    !id(v.version_id) ||
    !id(v.whatsapp_account_id) ||
    !count(v.revision)
  )
    return invalid();
  return {
    tenant_id: v.tenant_id,
    agent_instance_id: v.agent_instance_id,
    version_id: v.version_id,
    whatsapp_account_id: v.whatsapp_account_id,
    revision: v.revision,
  };
}
export function parsePublicationState(
  v: unknown,
  tenant: string,
  agent: string,
): PublicationState {
  if (
    !record(v) ||
    !count(v.draft_revision, 0) ||
    !count(v.company_revision, 0) ||
    !Array.isArray(v.blockers) ||
    !v.blockers.every(text) ||
    !Array.isArray(v.candidates) ||
    !Array.isArray(v.runs) ||
    !Array.isArray(v.accounts) ||
    !Array.isArray(v.versions) ||
    !Array.isArray(v.bindings) ||
    !Array.isArray(v.rollback_targets) ||
    !v.rollback_targets.every(id) ||
    !nullableText(v.next_cursor) ||
    !["candidates", "runs", "accounts", "versions"].includes(String(v.section))
  )
    return invalid();
  const candidates = v.candidates.map((c) => {
    if (
      !record(c) ||
      !record(c.source) ||
      c.source.source_kind !== "AGENT_CONFIGURATION" ||
      !count(c.source.revision) ||
      !count(c.source.company_revision) ||
      !digest(c.source.source_digest) ||
      !digest(c.source.code_digest)
    )
      return invalid();
    const version = parseVersion(c.version);
    if (
      c.source.version_id !== version.id ||
      c.source.agent_instance_id !== agent
    )
      return invalid();
    return {
      version,
      revision: c.source.revision,
      company_revision: c.source.company_revision,
    };
  });
  const runs = v.runs.map(parsePublicationRun),
    versions = v.versions.map(parseVersion),
    bindings = v.bindings.map(parseBinding);
  const accounts = v.accounts.map((a) => {
    if (
      !record(a) ||
      !id(a.id) ||
      !nullableText(a.display_phone_number) ||
      !text(a.status) ||
      !text(a.health_status)
    )
      return invalid();
    return {
      id: a.id,
      display_phone_number: a.display_phone_number,
      status: a.status,
      health_status: a.health_status,
      binding: a.binding === null ? null : parseBinding(a.binding),
      current_version:
        a.current_version === null ? null : parseVersion(a.current_version),
    };
  });
  if (
    accounts.some(
      (a) =>
        a.current_version &&
        (a.current_version.tenant_id !== tenant ||
          a.current_version.id !== a.binding?.version_id ||
          a.current_version.agent_instance_id !== a.binding?.agent_instance_id),
    )
  )
    return invalid();
  if (
    [...candidates.map((c) => c.version), ...versions].some(
      (s) => s.tenant_id !== tenant || s.agent_instance_id !== agent,
    ) ||
    runs.some((r) => r.agent_instance_id !== agent) ||
    [
      ...bindings,
      ...accounts.flatMap((a) => (a.binding ? [a.binding] : [])),
    ].some((b) => b.tenant_id !== tenant)
  )
    return invalid();
  return {
    draft_revision: v.draft_revision,
    company_revision: v.company_revision,
    blockers: v.blockers,
    candidates,
    runs,
    accounts,
    versions,
    bindings,
    rollback_targets: v.rollback_targets,
    next_cursor: v.next_cursor,
    section: String(v.section),
  };
}
export async function readPublication(
  tenant: string,
  agent: string,
  cursor?: string,
  section = "candidates",
): Promise<PublicationState> {
  if (
    !["candidates", "runs", "accounts", "versions"].includes(section) ||
    (cursor && cursor.length > 256)
  )
    return invalid();
  const query = new URLSearchParams({ section });
  if (cursor) query.set("cursor", cursor);
  return parsePublicationState(
    await callAuthenticatedBackend(
      `${publicationPath(tenant, agent)}?${query}`,
    ),
    tenant,
    agent,
  );
}
