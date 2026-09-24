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

export async function loadWhatsAppTestTemplates(
  tenantId: string,
  accountId: string,
) {
  try {
    const data = await callAuthenticatedBackend<
      { name: string; language: string }[]
    >(
      `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp/${encodeURIComponent(accountId)}/test-templates`,
      { method: "POST" },
    );
    return { ok: true as const, data };
  } catch (error) {
    return whatsappActionFailure(error);
  }
}

export async function sendWhatsAppTest(input: {
  tenantId: string;
  accountId: string;
  recipient: string;
  templateName: string;
  language: string;
  idempotencyKey: string;
}) {
  try {
    const data = await callAuthenticatedBackend<{ id: string; status: string }>(
      `/admin/tenants/${encodeURIComponent(input.tenantId)}/whatsapp/${encodeURIComponent(input.accountId)}/test-messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recipient: input.recipient,
          template_name: input.templateName,
          language: input.language,
          idempotency_key: input.idempotencyKey,
        }),
      },
    );
    return { ok: true as const, data };
  } catch (error) {
    return whatsappActionFailure(error);
  }
}

export async function getWhatsAppTestStatus(
  tenantId: string,
  accountId: string,
  messageId: string,
) {
  try {
    const data = await callAuthenticatedBackend<{
      id: string;
      status: string;
      provider_message_id: string | null;
    }>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp/${encodeURIComponent(accountId)}/test-messages/${encodeURIComponent(messageId)}`,
    );
    return { ok: true as const, data };
  } catch (error) {
    return whatsappActionFailure(error);
  }
}

export async function beginWhatsAppSignup(
  tenantId: string,
  mode: "API_ONLY" | "COEXISTENCE" = "API_ONLY",
): Promise<ActionResult<SignupStart>> {
  try {
    const data = await callAuthenticatedBackend<SignupStart>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp/signup/start`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) },
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
  mode: "API_ONLY" | "COEXISTENCE";
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
          mode: input.mode,
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

export async function saveOnboardingStep(formData: FormData): Promise<void> {
  const tenantId = formData.get("tenantId");
  const step = formData.get("step");
  const revision = Number(formData.get("expectedRevision"));
  if (
    typeof tenantId !== "string" ||
    typeof step !== "string" ||
    !Number.isInteger(revision) ||
    revision < 0
  ) {
    redirect("/?error=invalid-onboarding-request");
  }

  let errorCode: string | null = null;
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/onboarding/${encodeURIComponent(step)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: revision,
          data: onboardingStepData(step, formData),
        }),
      },
    );
    revalidatePath(`/tenants/${tenantId}/onboarding`);
  } catch (error) {
    errorCode =
      error instanceof BackendProblem ? error.code : "onboarding_save_failed";
  }

  if (errorCode) {
    redirect(
      `/tenants/${tenantId}/onboarding/${step}?error=${encodeURIComponent(errorCode)}`,
    );
  }
  redirect(`/tenants/${tenantId}/onboarding/${step}?saved=1`);
}

function onboardingStepData(
  step: string,
  formData: FormData,
): Record<string, unknown> {
  switch (step) {
    case "company":
      return {
        legal_name: textValue(formData, "legal_name"),
        commercial_name: textValue(formData, "commercial_name"),
        country: textValue(formData, "country"),
        city: textValue(formData, "city"),
        industry: textValue(formData, "industry"),
        timezone: textValue(formData, "timezone"),
        primary_locale: textValue(formData, "primary_locale"),
        business_description: textValue(formData, "business_description"),
        service_hours: textValue(formData, "service_hours"),
        whatsapp_volume: textValue(formData, "whatsapp_volume") || "unknown",
        responsible_person: textValue(formData, "responsible_person"),
        privacy_contact: textValue(formData, "privacy_contact"),
        incident_contact: textValue(formData, "incident_contact"),
      };
    case "agent":
      return {
        agent_name: textValue(formData, "agent_name"),
        greeting_style: textValue(formData, "greeting_style"),
        tone: textValue(formData, "tone"),
        formality: textValue(formData, "formality"),
        greeting: textValue(formData, "greeting"),
        instructions: textValue(formData, "instructions"),
        supported_languages: listValues(formData, "supported_languages"),
        brand_vocabulary: textValue(formData, "brand_vocabulary"),
      };
    case "capabilities": {
      const unsupported = textValue(formData, "unsupported_requirement");
      return {
        use_cases: listValues(formData, "use_cases"),
        selected_capabilities: listValues(formData, "selected_capabilities"),
        unsupported_requirements: unsupported
          ? [
              {
                description: unsupported,
                classification: textValue(
                  formData,
                  "unsupported_classification",
                ),
              },
            ]
          : [],
        onboarding_classification: textValue(
          formData,
          "onboarding_classification",
        ),
      };
    }
    case "integrations":
      return {
        business_systems_required: nullableBoolean(
          textValue(formData, "business_systems_required"),
        ),
        required_connectors: listValues(formData, "required_connectors"),
        connection_notes: textValue(formData, "connection_notes"),
      };
    case "knowledge":
      return {
        source_name: textValue(formData, "source_name"),
        source_type: textValue(formData, "source_type"),
        source_reference: textValue(formData, "source_reference"),
        authority: textValue(formData, "authority"),
        approved_summary: textValue(formData, "approved_summary"),
        critical_conflicts: Number(
          textValue(formData, "critical_conflicts") || 0,
        ),
        review_confirmed: formData.get("review_confirmed") === "true",
      };
    case "policies-identity":
      return {
        pricing_response: nullableText(formData, "pricing_response"),
        privacy_policy_status: nullableText(formData, "privacy_policy_status"),
        customer_identity_method: nullableText(
          formData,
          "customer_identity_method",
        ),
        policy_notes: textValue(formData, "policy_notes"),
      };
    case "human-operations":
      return {
        handoff_enabled: nullableBoolean(
          textValue(formData, "handoff_enabled"),
        ),
        response_surface: textValue(formData, "response_surface"),
        support_hours: textValue(formData, "support_hours"),
        awaiting_human_policy: textValue(formData, "awaiting_human_policy"),
      };
    case "approval-routes":
      return {
        high_risk_actions_expected: nullableBoolean(
          textValue(formData, "high_risk_actions_expected"),
        ),
        approver_emails: textValue(formData, "approver_emails")
          .split(/[\n,;]/)
          .map((value) => value.trim())
          .filter(Boolean),
        strategy: "FIRST_RESPONSE",
        route_notes: textValue(formData, "route_notes"),
      };
    default:
      throw new Error("This onboarding step is read-only.");
  }
}

function textValue(formData: FormData, key: string): string {
  const value = formData.get(key);
  return typeof value === "string" ? value.trim() : "";
}

function nullableText(formData: FormData, key: string): string | null {
  return textValue(formData, key) || null;
}

function listValues(formData: FormData, key: string): string[] {
  return formData
    .getAll(key)
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim())
    .filter(Boolean);
}

function nullableBoolean(value: string): boolean | null {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

function whatsappActionFailure(error: unknown): ActionResult<never> {
  if (error instanceof BackendProblem) {
    const messages: Record<string, string> = {
      whatsapp_coexistence_not_ready:
        "La coexistencia todavía no está habilitada. Conserva tu cuenta en el celular; no se ha cambiado al modo exclusivo.",
      whatsapp_coexistence_ineligible:
        "Meta no confirmó la coexistencia para este número. No lo cambiaremos al modo exclusivo.",
      whatsapp_test_unavailable:
        "No se pudo preparar la prueba. Comprueba que la cuenta esté conectada y tenga permiso para consultar sus plantillas.",
      template_policy_violation:
        "La plantilla no está disponible para esta cuenta. Vuelve a cargar las plantillas desde Meta.",
      approved_template_required:
        "Meta debe aprobar la plantilla antes de enviarla.",
      authentication_required: "Vuelve a iniciar sesión para continuar.",
    };
    if (messages[error.code])
      return { ok: false, message: messages[error.code] };
  }
  if (
    error instanceof BackendProblem &&
    error.code === "meta_signup_not_configured"
  ) {
    return {
      ok: false,
      message: "Falta completar la configuración de Meta para AI Workers.",
    };
  }
  return {
    ok: false,
    message:
      "No se pudo completar la operación de WhatsApp. Revisa la conexión e inténtalo de nuevo.",
  };
}
