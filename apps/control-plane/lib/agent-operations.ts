import "server-only";
import { callAuthenticatedBackend } from "./api";
import { isWorkspaceId } from "./agent-workspace";

export type AgentOperationView = {
  tenant_id: string;
  agent_instance_id: string;
  enabled: boolean;
  revision: number;
  resumed_at: string | null;
  updated_at: string;
  controls_available: boolean;
};
export type OperationActionState = {
  status: "idle" | "success" | "error" | "conflict" | "validation";
  message?: string;
  operation?: AgentOperationView;
  requiresRefresh?: boolean;
};
function operationPath(tenant: string, agent: string) {
  if (!isWorkspaceId(tenant) || !isWorkspaceId(agent))
    throw new Error("invalid_operation_scope");
  return `/admin/agent-workspace/companies/${tenant}/agents/${agent}/operation`;
}
const timestamp = (value: unknown): value is string =>
  typeof value === "string" &&
  /^\d{4}-\d{2}-\d{2}T/.test(value) &&
  Number.isFinite(Date.parse(value));
function parseOperation(
  value: unknown,
  tenant: string,
  agent: string,
): AgentOperationView {
  if (value === null || typeof value !== "object")
    throw new Error("invalid_operation_response");
  const row = value as Record<string, unknown>;
  if (
    row.tenant_id !== tenant ||
    row.agent_instance_id !== agent ||
    typeof row.enabled !== "boolean" ||
    !Number.isSafeInteger(row.revision) ||
    Number(row.revision) < 1 ||
    !timestamp(row.updated_at) ||
    !(row.resumed_at === null || timestamp(row.resumed_at)) ||
    !(
      row.controls_available === undefined ||
      typeof row.controls_available === "boolean"
    )
  )
    throw new Error("invalid_operation_response");
  return {
    tenant_id: tenant,
    agent_instance_id: agent,
    enabled: row.enabled,
    revision: Number(row.revision),
    resumed_at: row.resumed_at as string | null,
    updated_at: row.updated_at,
    controls_available: row.controls_available === true,
  };
}
export async function readAgentOperation(
  tenant: string,
  agent: string,
): Promise<AgentOperationView> {
  return parseOperation(
    await callAuthenticatedBackend(operationPath(tenant, agent)),
    tenant,
    agent,
  );
}
export async function setAgentOperation(
  tenant: string,
  agent: string,
  enabled: boolean,
  expectedRevision: number,
): Promise<AgentOperationView> {
  if (
    typeof enabled !== "boolean" ||
    !Number.isSafeInteger(expectedRevision) ||
    expectedRevision < 1
  )
    throw new Error("invalid_operation_request");
  const result = parseOperation(
    await callAuthenticatedBackend(operationPath(tenant, agent), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, expected_revision: expectedRevision }),
    }),
    tenant,
    agent,
  );
  if (result.enabled !== enabled) throw new Error("operation_result_mismatch");
  return result;
}
