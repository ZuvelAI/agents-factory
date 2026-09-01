"use server";

import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import {
  authenticateWithPassword,
  createServerSupabaseClient,
  signOutServerSession,
} from "../lib/auth";
import { BackendProblem, callAuthenticatedBackend } from "../lib/api";
import type { Tenant } from "../lib/tenant";

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

export async function createTenant(formData: FormData): Promise<void> {
  const payload = {
    slug: requiredValue(formData, "slug"),
    name: requiredValue(formData, "name"),
    legal_name: requiredValue(formData, "legalName"),
    industry: requiredValue(formData, "industry"),
    timezone: requiredValue(formData, "timezone"),
    locale: requiredValue(formData, "locale"),
  };
  let tenant: Tenant;
  try {
    tenant = await callAuthenticatedBackend<Tenant>("/admin/tenants", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": randomUUID(),
      },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    redirect(`/tenants/new?error=${actionError(error)}`);
  }
  redirect(`/tenants/${tenant.id}`);
}

export async function updateTenantProfile(formData: FormData): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: Number(requiredValue(formData, "revision")),
          name: requiredValue(formData, "name"),
          legal_name: requiredValue(formData, "legalName"),
          industry: requiredValue(formData, "industry"),
          timezone: requiredValue(formData, "timezone"),
          locale: requiredValue(formData, "locale"),
        }),
      },
    );
  } catch (error) {
    redirect(
      `/tenants/${tenantId}/settings?error=${actionError(error, "tenant_profile_stale")}`,
    );
  }
  revalidatePath(`/tenants/${tenantId}`);
  redirect(`/tenants/${tenantId}/settings?saved=profile`);
}

export async function createCustomerServiceDraft(
  formData: FormData,
): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/customer-service`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_name: requiredValue(formData, "businessName"),
        }),
      },
    );
  } catch (error) {
    redirect(`/tenants/${tenantId}/agent?error=${actionError(error)}`);
  }
  revalidatePath(`/tenants/${tenantId}/agent`);
  redirect(`/tenants/${tenantId}/agent?created=1`);
}

export async function updateAgentPresentation(
  formData: FormData,
): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  const instanceId = requiredValue(formData, "instanceId");
  const section = requiredValue(formData, "section");
  const payload: Record<string, unknown> = {
    expected_version_id: requiredValue(formData, "versionId"),
  };
  if (section === "persona") {
    payload.agent_name = optionalValue(formData, "agentName");
    payload.tone = requiredValue(formData, "tone");
    payload.formality = requiredValue(formData, "formality");
    payload.greeting = requiredValue(formData, "greeting");
    payload.brand_vocabulary = (
      optionalValue(formData, "brandVocabulary") ?? ""
    )
      .split(/[\n,]/)
      .map((value) => value.trim())
      .filter(Boolean);
  } else {
    payload.supported_locales = formData
      .getAll("supportedLocales")
      .filter((value): value is string => typeof value === "string");
    payload.default_locale = requiredValue(formData, "defaultLocale");
  }
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/${encodeURIComponent(instanceId)}/presentation-drafts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
  } catch (error) {
    redirect(
      `/tenants/${tenantId}/agent?error=${actionError(error, "agent_spec_stale_write")}`,
    );
  }
  revalidatePath(`/tenants/${tenantId}/agent`);
  redirect(`/tenants/${tenantId}/agent?saved=${section}`);
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

function requiredValue(formData: FormData, name: string): string {
  const value = formData.get(name);
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Missing form field: ${name}`);
  }
  return value.trim();
}

function optionalValue(formData: FormData, name: string): string | null {
  const value = formData.get(name);
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function actionError(error: unknown, staleCode?: string): string {
  if (error instanceof BackendProblem && error.code === staleCode)
    return "stale";
  return "request";
}
