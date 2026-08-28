"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import {
  authenticateWithPassword,
  createServerSupabaseClient,
  signOutServerSession,
} from "../lib/auth";
import { BackendProblem, callAuthenticatedBackend } from "../lib/api";

export async function login(formData: FormData): Promise<void> {
  const email = formData.get("email");
  const submittedPassword = formData.get("password");
  if (typeof email !== "string" || typeof submittedPassword !== "string") {
    redirect("/login?error=invalid");
  }

  const client = await createServerSupabaseClient();
  const result = await authenticateWithPassword(client, {
    email,
    ["password"]: submittedPassword,
  });
  if (!result.ok) redirect("/login?error=invalid");
  redirect("/");
}

export async function logout(): Promise<void> {
  const client = await createServerSupabaseClient();
  await signOutServerSession(client);
  redirect("/login");
}

type SignupStart = {
  app_id: string;
  configuration_id: string;
  redirect_uri: string;
  state: string;
  expires_at: string;
};

type ActionResult<T = undefined> =
  | { ok: true; data: T }
  | { ok: false; message: string };

export async function beginWhatsAppSignup(
  tenantId: string,
): Promise<ActionResult<SignupStart>> {
  try {
    const data = await callAuthenticatedBackend<SignupStart>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp/signup/start`,
      { method: "POST" },
    );
    return { ok: true, data };
  } catch (error) {
    return whatsappActionFailure(error);
  }
}

export async function finishWhatsAppSignup(input: {
  tenantId: string;
  state: string;
  code: string;
  businessId: string;
  wabaId: string;
  phoneNumberId: string;
}): Promise<ActionResult> {
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(input.tenantId)}/whatsapp/signup/complete`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          state: input.state,
          code: input.code,
          business_id: input.businessId,
          waba_id: input.wabaId,
          phone_number_id: input.phoneNumberId,
          mode: "API_ONLY",
        }),
      },
    );
    revalidatePath(`/tenants/${input.tenantId}/whatsapp`);
    return { ok: true, data: undefined };
  } catch (error) {
    return whatsappActionFailure(error);
  }
}

export async function refreshWhatsAppHealth(formData: FormData): Promise<void> {
  const tenantId = formData.get("tenantId");
  const accountId = formData.get("accountId");
  if (typeof tenantId !== "string" || typeof accountId !== "string") return;
  await callAuthenticatedBackend(
    `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp/${encodeURIComponent(accountId)}/health`,
    { method: "POST" },
  );
  revalidatePath(`/tenants/${tenantId}/whatsapp`);
}

export async function revokeWhatsAppAccount(formData: FormData): Promise<void> {
  const tenantId = formData.get("tenantId");
  const accountId = formData.get("accountId");
  if (typeof tenantId !== "string" || typeof accountId !== "string") return;
  await callAuthenticatedBackend(
    `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp/${encodeURIComponent(accountId)}/revoke`,
    { method: "POST" },
  );
  revalidatePath(`/tenants/${tenantId}/whatsapp`);
}

function whatsappActionFailure(error: unknown): ActionResult<never> {
  if (
    error instanceof BackendProblem &&
    error.code === "meta_signup_not_configured"
  ) {
    return {
      ok: false,
      message: "Meta Embedded Signup is not configured in this environment.",
    };
  }
  return {
    ok: false,
    message: "The WhatsApp connection could not be completed.",
  };
}
