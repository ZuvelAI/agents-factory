import { expect, it, vi } from "vitest";
import {
  publicationAction,
  refreshPublication,
} from "../../components/agent-workspace/publication-actions";
import { readPublication } from "../../lib/workspace-publication";
import { callAuthenticatedBackend } from "../../lib/api";
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("../../lib/api", async (original) => ({
  ...(await original<typeof import("../../lib/api")>()),
  callAuthenticatedBackend: vi.fn(async () => {
    throw new Error(
      "A request without confirmation must not reach the backend",
    );
  }),
}));
vi.mock("../../lib/workspace-publication", async (original) => ({
  ...(await original<typeof import("../../lib/workspace-publication")>()),
  readPublication: vi.fn(async () => {
    throw new Error("state GET unavailable");
  }),
}));
function form(command: string) {
  const f = new FormData();
  f.set("tenantId", "019c2000-0000-7000-8000-000000000102");
  f.set("agentId", "019c2000-0000-7000-8000-000000000501");
  f.set("command", command);
  return f;
}
it("requires explicit publication confirmation before any request", async () => {
  const result = await publicationAction({ status: "idle" }, form("publish"));
  expect(result.status).toBe("validation");
});
it("requires explicit rollback confirmation before any request", async () => {
  const result = await publicationAction({ status: "idle" }, form("rollback"));
  expect(result.status).toBe("validation");
});
it("preserves an accepted run even when its following state GET fails", async () => {
  const run = {
    id: "019c2000-0000-7000-8000-000000000701",
    version_id: "019c2000-0000-7000-8000-000000000702",
    agent_instance_id: "019c2000-0000-7000-8000-000000000501",
    source_kind: "AGENT_CONFIGURATION",
    draft_revision: 1,
    run_kind: "PREVIEW",
    is_current: true,
    approved: null,
    expires_at: "2099-01-01T00:00:00Z",
    input_messages: [{ role: "user", text: "Hola" }],
    result: null,
  };
  vi.mocked(callAuthenticatedBackend).mockResolvedValueOnce(run as never);
  const f = form("preview");
  f.set("revision", "1");
  f.set("versionId", run.version_id);
  f.set("requestKey", run.id);
  f.set("messages", JSON.stringify(run.input_messages));
  const result = await publicationAction({ status: "idle" }, f);
  expect(result.run?.id).toBe(run.id);
  expect(result.status).toBe("success");
});
it("refresh preserves the page cursor and section", async () => {
  await refreshPublication(
    "019c2000-0000-7000-8000-000000000102",
    "019c2000-0000-7000-8000-000000000501",
    "page-two",
    "runs",
  );
  expect(readPublication).toHaveBeenLastCalledWith(
    "019c2000-0000-7000-8000-000000000102",
    "019c2000-0000-7000-8000-000000000501",
    "page-two",
    "runs",
  );
});
