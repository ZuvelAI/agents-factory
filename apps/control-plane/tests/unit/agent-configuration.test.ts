import { expect, it, vi } from "vitest";
import { parseDraft } from "../../lib/agent-configuration";
import { saveAgentConfiguration } from "../../components/agent-workspace/configuration-actions";
import { callAuthenticatedBackend, BackendProblem } from "../../lib/api";

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("../../lib/api", async (original) => ({
  ...(await original<typeof import("../../lib/api")>()),
  callAuthenticatedBackend: vi.fn(),
}));

const tenant = "019c2000-0000-7000-8000-000000000102";
const agent = "019c2000-0000-7000-8000-000000000501";

it("rejects malformed draft contracts and unsupported models", () => {
  expect(() => parseDraft({})).toThrow();
  expect(() =>
    parseDraft({ configuration: { agent: { model: "unknown" } } }),
  ).toThrow();
});

it("preserves submitted text on revision conflict without retrying a write", async () => {
  const backend = vi.mocked(callAuthenticatedBackend);
  backend.mockReset();
  backend.mockRejectedValue(
    new BackendProblem({
      status: 409,
      code: "configuration_revision_conflict",
      message: "Reload",
    }),
  );
  const form = new FormData();
  form.set("tenantId", tenant);
  form.set("agentId", agent);
  form.set("revision", "2");
  form.set(
    "configuration",
    JSON.stringify({ agent: { instructions: "Mi texto sin guardar" } }),
  );
  const result = await saveAgentConfiguration({ status: "idle" }, form);
  expect(result.status).toBe("conflict");
  expect(result.submitted).toContain("Mi texto sin guardar");
  expect(
    backend.mock.calls.filter(([, options]) => options?.method === "PUT"),
  ).toHaveLength(1);
});
