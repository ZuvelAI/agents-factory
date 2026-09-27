import { beforeEach, describe, expect, it, vi } from "vitest";

import { resumeCoexistenceConversation } from "../../app/actions";
import { BackendProblem, callAuthenticatedBackend } from "../../lib/api";

vi.mock("../../lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../lib/api")>();
  return { ...original, callAuthenticatedBackend: vi.fn() };
});
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: (path: string) => {
    throw new Error(`redirect:${path}`);
  },
}));

const getBackend = vi.mocked(callAuthenticatedBackend);
const tenantId = "019c2000-0000-7000-8000-000000000101";
const accountId = "019c2000-0000-7000-8000-000000000202";
const conversationId = "019c2000-0000-7000-8000-000000000303";

function resumeForm(): FormData {
  const form = new FormData();
  form.set("tenantId", tenantId);
  form.set("accountId", accountId);
  form.set("conversationId", conversationId);
  form.set("expectedVersion", "3");
  return form;
}

beforeEach(() => {
  getBackend.mockReset();
});

describe("coexistence resume action", () => {
  it("rejects a submission without an explicit confirmation before contacting the backend", async () => {
    const form = resumeForm();
    getBackend.mockResolvedValue(undefined);

    await expect(resumeCoexistenceConversation(form)).rejects.toThrow(
      "redirect:/?error=invalid-whatsapp-request",
    );
    expect(getBackend).not.toHaveBeenCalled();
  });

  it("posts the visible version for exactly one conversation", async () => {
    const form = resumeForm();
    form.set("confirmed", "resume");
    getBackend.mockResolvedValue(undefined);

    await expect(resumeCoexistenceConversation(form)).rejects.toThrow(
      `redirect:/tenants/${tenantId}/whatsapp?humanControl=resumed`,
    );
    expect(getBackend).toHaveBeenCalledWith(
      `/admin/tenants/${tenantId}/whatsapp/${accountId}/conversations/${conversationId}/resume-ai`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: '{"expected_version":3}',
      },
    );
  });

  it("reports a changed conversation instead of claiming successful reactivation", async () => {
    const form = resumeForm();
    form.set("confirmed", "resume");
    getBackend.mockRejectedValue(
      new BackendProblem({
        status: 409,
        code: "conversation_control_conflict",
        message: "Conversation changed",
      }),
    );

    await expect(resumeCoexistenceConversation(form)).rejects.toThrow(
      `redirect:/tenants/${tenantId}/whatsapp?humanControl=stale`,
    );
  });
});
