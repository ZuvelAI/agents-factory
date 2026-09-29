import { beforeEach, describe, expect, it, vi } from "vitest";

import { resolveAccountUpdateAlert } from "../../app/(authenticated)/operations/alert-actions";
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

const backend = vi.mocked(callAuthenticatedBackend);
const alertId = "019c2000-0000-7000-8000-000000000777";

function resolutionForm(note = "Checked in Meta"): FormData {
  const form = new FormData();
  form.set("alertId", alertId);
  form.set("note", note);
  form.set("confirmed", "resolve");
  return form;
}

beforeEach(() => {
  backend.mockReset();
});

describe("Operations alert resolution action", () => {
  it("rejects invalid form data before contacting the backend", async () => {
    const cases = [
      new FormData(),
      resolutionForm(" "),
      resolutionForm("x".repeat(501)),
      resolutionForm("Valid"),
    ];
    cases[3].set("alertId", "not-a-uuid");
    for (const form of cases) {
      await expect(resolveAccountUpdateAlert(form)).rejects.toThrow(
        "redirect:/operations?alertResolution=invalid",
      );
    }
    expect(backend).not.toHaveBeenCalled();
  });

  it("posts only the note once after explicit confirmation", async () => {
    backend.mockResolvedValue({});
    await expect(resolveAccountUpdateAlert(resolutionForm())).rejects.toThrow(
      "redirect:/operations?alertResolution=resolved",
    );
    expect(backend).toHaveBeenCalledTimes(1);
    expect(backend).toHaveBeenCalledWith(
      `/admin/whatsapp/account-update-alerts/${alertId}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: '{"note":"Checked in Meta"}',
      },
    );
  });

  it("distinguishes a conflict from an unavailable backend", async () => {
    backend.mockRejectedValueOnce(
      new BackendProblem({ status: 409, code: "conflict", message: "Closed" }),
    );
    await expect(resolveAccountUpdateAlert(resolutionForm())).rejects.toThrow(
      "redirect:/operations?alertResolution=conflict",
    );

    backend.mockRejectedValueOnce(new Error("offline"));
    await expect(resolveAccountUpdateAlert(resolutionForm())).rejects.toThrow(
      "redirect:/operations?alertResolution=error",
    );
  });
});
