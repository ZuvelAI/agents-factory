"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { BackendProblem, callAuthenticatedBackend } from "../../../lib/api";

const UUID_PATTERN = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

export async function resolveAccountUpdateAlert(
  formData: FormData,
): Promise<void> {
  const alertId = formData.get("alertId");
  const rawNote = formData.get("note");
  const confirmed = formData.get("confirmed");
  const note = typeof rawNote === "string" ? rawNote.trim() : "";

  if (
    typeof alertId !== "string" ||
    !UUID_PATTERN.test(alertId) ||
    !note ||
    note.length > 500 ||
    confirmed !== "resolve"
  ) {
    redirect("/operations?alertResolution=invalid");
  }

  let outcome: "resolved" | "conflict" | "error" = "resolved";
  try {
    await callAuthenticatedBackend(
      `/admin/whatsapp/account-update-alerts/${alertId}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
      },
    );
  } catch (error) {
    outcome =
      error instanceof BackendProblem && error.status === 409
        ? "conflict"
        : "error";
  }

  revalidatePath("/operations");
  redirect(`/operations?alertResolution=${outcome}`);
}
