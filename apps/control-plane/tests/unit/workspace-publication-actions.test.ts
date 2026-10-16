import { expect, it, vi } from "vitest";
import { publicationAction } from "../../components/agent-workspace/publication-actions";
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("../../lib/api", async (original) => ({
  ...(await original<typeof import("../../lib/api")>()),
  callAuthenticatedBackend: async () => {
    throw new Error(
      "A request without confirmation must not reach the backend",
    );
  },
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
