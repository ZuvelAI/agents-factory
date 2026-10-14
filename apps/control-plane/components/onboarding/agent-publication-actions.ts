"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { BackendProblem, callAuthenticatedBackend } from "../../lib/api";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function id(form: FormData, name: string): string {
  const value = form.get(name);
  if (typeof value !== "string" || !uuid.test(value))
    throw new Error("invalid_input");
  return value;
}
function revision(form: FormData, name: string, min = 1): number {
  const raw = form.get(name);
  if (typeof raw !== "string" || !/^\d+$/.test(raw))
    throw new Error("invalid_input");
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < min)
    throw new Error("invalid_input");
  return value;
}
async function execute(
  form: FormData,
  kind: "prepare" | "test" | "review" | "publish" | "rollback",
): Promise<void> {
  let tenant: string;
  try {
    tenant = id(form, "tenantId");
  } catch {
    redirect("/tenants?error=invalid-publication-input");
  }
  let step = "test",
    suffix = "",
    payload: Record<string, unknown> = {},
    query = "",
    failure: string | null = null;
  try {
    if (kind === "prepare")
      payload = { expected_revision: revision(form, "expectedRevision") };
    if (kind === "test") suffix = `/candidates/${id(form, "versionId")}/tests`;
    if (kind === "review") {
      const decision = form.get("decision");
      if (decision !== "approve" && decision !== "reject")
        throw new Error("invalid_input");
      if (decision === "approve" && form.get("confirmReview") !== "on")
        throw new Error("review_confirmation_required");
      suffix = `/tests/${id(form, "runId")}/review`;
      payload = {
        approved: decision === "approve",
        expected_revision: revision(form, "expectedRevision"),
      };
      query = `?run=${id(form, "runId")}`;
      step = decision === "approve" ? "production" : "quality-gate";
    }
    if (kind === "publish") {
      step = "production";
      if (form.get("confirmPublish") !== "on")
        throw new Error("publication_confirmation_required");
      suffix = "/publish";
      payload = {
        version_id: id(form, "versionId"),
        whatsapp_account_id: id(form, "accountId"),
        expected_revision: revision(form, "expectedRevision"),
        test_run_id: id(form, "runId"),
        expected_binding_revision: revision(form, "expectedBindingRevision", 0),
      };
      query = `?run=${id(form, "runId")}`;
    }
    if (kind === "rollback") {
      step = "production";
      if (form.get("confirmRollback") !== "on")
        throw new Error("rollback_confirmation_required");
      suffix = "/rollback";
      payload = {
        whatsapp_account_id: id(form, "accountId"),
        target_version_id: id(form, "versionId"),
        expected_binding_revision: revision(form, "expectedBindingRevision"),
      };
    }
    if (kind === "prepare") suffix = "/candidates";
    const result = await callAuthenticatedBackend<{ id?: string }>(
      `/admin/tenants/${tenant}/agent-publication${suffix}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    if (kind === "prepare" && result.id && uuid.test(result.id))
      query = `?candidate=${result.id}`;
    if (kind === "test" && result.id && uuid.test(result.id))
      query = `?run=${result.id}`;
  } catch (error) {
    failure =
      error instanceof BackendProblem
        ? error.code
        : "publication_action_failed";
  }
  const path = `/tenants/${tenant}/onboarding`;
  revalidatePath(path);
  if (failure)
    redirect(`${path}/${step}?publicationError=${encodeURIComponent(failure)}`);
  redirect(`${path}/${step}${query}`);
}

export async function prepareAgentCandidate(form: FormData): Promise<void> {
  return execute(form, "prepare");
}
export async function testAgentCandidate(form: FormData): Promise<void> {
  return execute(form, "test");
}
export async function reviewAgentTests(form: FormData): Promise<void> {
  return execute(form, "review");
}
export async function publishAgentCandidate(form: FormData): Promise<void> {
  return execute(form, "publish");
}
export async function rollbackAgent(form: FormData): Promise<void> {
  return execute(form, "rollback");
}
