import { beforeEach, expect, it, vi } from "vitest";
import { BackendProblem, callAuthenticatedBackend } from "../../lib/api";
import {
  readAgentOperation,
  setAgentOperation,
} from "../../lib/agent-operations";
import { operationAction } from "../../components/agent-workspace/operation-actions";

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("../../lib/api", async (original) => ({
  ...(await original<typeof import("../../lib/api")>()),
  callAuthenticatedBackend: vi.fn(),
}));
const backend = vi.mocked(callAuthenticatedBackend);
const tenant = "019c2000-0000-7000-8000-000000000102";
const agent = "019c2000-0000-7000-8000-000000000501";
const operation = {
  tenant_id: tenant,
  agent_instance_id: agent,
  enabled: false,
  revision: 2,
  resumed_at: null,
  updated_at: "2026-10-21T12:00:00Z",
  controls_available: true,
};
beforeEach(() => {
  backend.mockReset();
});
function form(command = "pause", confirmed = true) {
  const data = new FormData();
  data.set("tenantId", tenant);
  data.set("agentId", agent);
  data.set("command", command);
  data.set("revision", "1");
  if (confirmed) data.set("confirmOperation", "yes");
  return data;
}
it("requires confirmation before pausing or resuming", async () => {
  for (const command of ["pause", "resume"]) {
    expect(
      (await operationAction({ status: "idle" }, form(command, false))).status,
    ).toBe("validation");
  }
  expect(backend).not.toHaveBeenCalled();
});
it("sends exact tenant agent and optimistic revision", async () => {
  backend.mockResolvedValue(operation);
  expect(await setAgentOperation(tenant, agent, false, 1)).toEqual(operation);
  expect(backend).toHaveBeenCalledWith(
    `/admin/agent-workspace/companies/${tenant}/agents/${agent}/operation`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ enabled: false, expected_revision: 1 }),
    }),
  );
});
it("rejects foreign identity and malformed operation data", async () => {
  for (const bad of [
    { ...operation, tenant_id: agent },
    { ...operation, revision: 0 },
    { ...operation, enabled: "false" },
    { ...operation, updated_at: "invalid" },
  ]) {
    backend.mockResolvedValueOnce(bad);
    await expect(readAgentOperation(tenant, agent)).rejects.toThrow();
  }
  await expect(readAgentOperation("../private", agent)).rejects.toThrow();
});
it("does not enable controls from an older backend response", async () => {
  backend.mockResolvedValue({ ...operation, controls_available: undefined });
  expect((await readAgentOperation(tenant, agent)).controls_available).toBe(
    false,
  );
});
it("reports conflict without pretending the operation succeeded", async () => {
  backend.mockRejectedValue(
    new BackendProblem({
      status: 409,
      code: "agent_operation_revision_conflict",
      message: "private diagnostic",
    }),
  );
  const result = await operationAction({ status: "idle" }, form());
  expect(result.status).toBe("conflict");
  expect(result.operation).toBeUndefined();
  expect(result.message).not.toContain("private diagnostic");
});
it("does not leak failure details or confirm an uncertain mutation", async () => {
  backend.mockRejectedValue(new Error("SECRET_INTERNAL_DIAGNOSTIC"));
  const result = await operationAction({ status: "idle" }, form());
  expect(result.status).toBe("error");
  expect(result.requiresRefresh).toBe(true);
  expect(result.operation).toBeUndefined();
  expect(result.message).not.toContain("SECRET_INTERNAL_DIAGNOSTIC");
});
it("refresh reads current state without posting another transition", async () => {
  backend.mockResolvedValue(operation);
  const result = await operationAction(
    { status: "idle" },
    form("refresh", false),
  );
  expect(result.operation).toEqual(operation);
  expect(backend).toHaveBeenCalledTimes(1);
  expect(backend).toHaveBeenCalledWith(expect.stringContaining("/operation"));
});
