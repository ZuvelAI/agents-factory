import { beforeEach, expect, it, vi } from "vitest";
import {
  publishAgentCandidate,
  reviewAgentTests,
} from "../../components/onboarding/agent-publication-actions";
import { callAuthenticatedBackend } from "../../lib/api";
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: (path: string) => {
    throw new Error(`redirect:${path}`);
  },
}));
vi.mock("../../lib/api", () => ({
  callAuthenticatedBackend: vi.fn(),
  BackendProblem: class extends Error {
    code = "authentication_required";
  },
}));
const backend = vi.mocked(callAuthenticatedBackend);
const tenant = "019c2000-0000-7000-8000-000000000111";
function form() {
  const f = new FormData();
  for (const [key, value] of Object.entries({
    tenantId: tenant,
    versionId: tenant,
    runId: tenant,
    accountId: tenant,
    expectedRevision: "3",
    expectedBindingRevision: "2",
  }))
    f.set(key, value);
  return f;
}
beforeEach(() => {
  backend.mockReset();
});
it("does not publish without explicit confirmation", async () => {
  await expect(publishAgentCandidate(form())).rejects.toThrow(
    "publicationError",
  );
  expect(backend).not.toHaveBeenCalled();
});
it("passes account and configuration revisions to authenticated backend", async () => {
  const f = form();
  f.set("confirmPublish", "on");
  backend.mockResolvedValue({});
  await expect(publishAgentCandidate(f)).rejects.toThrow(
    `/tenants/${tenant}/onboarding/production`,
  );
  expect(backend).toHaveBeenCalledWith(
    `/admin/tenants/${tenant}/agent-publication/publish`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        version_id: tenant,
        whatsapp_account_id: tenant,
        expected_revision: 3,
        test_run_id: tenant,
        expected_binding_revision: 2,
      }),
    }),
  );
});
it("requires human review confirmation before approval", async () => {
  const f = form();
  f.set("decision", "approve");
  await expect(reviewAgentTests(f)).rejects.toThrow("publicationError");
  expect(backend).not.toHaveBeenCalled();
});
it("rejects malformed ids without invoking backend", async () => {
  const f = form();
  f.set("confirmPublish", "on");
  f.set("accountId", "../../other");
  await expect(publishAgentCandidate(f)).rejects.toThrow("publicationError");
  expect(backend).not.toHaveBeenCalled();
});
