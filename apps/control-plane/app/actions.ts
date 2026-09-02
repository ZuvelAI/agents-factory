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

export async function updateTenantCapabilities(
  formData: FormData,
): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  const instanceId = requiredValue(formData, "instanceId");
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/${encodeURIComponent(instanceId)}/capability-drafts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_version_id: requiredValue(formData, "versionId"),
          capability_names: formData
            .getAll("capabilityNames")
            .filter((value): value is string => typeof value === "string"),
        }),
      },
    );
  } catch (error) {
    redirect(
      `/tenants/${tenantId}/capabilities?error=${actionError(error, "agent_spec_stale_write")}`,
    );
  }
  revalidatePath(`/tenants/${tenantId}`);
  redirect(`/tenants/${tenantId}/capabilities?saved=capabilities`);
}

export async function updateTenantPolicies(formData: FormData): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  const instanceId = requiredValue(formData, "instanceId");
  const policies = formData
    .getAll("policyActions")
    .filter((value): value is string => typeof value === "string")
    .map((action) => ({
      action,
      identity_level: Number(requiredValue(formData, `identity:${action}`)),
      confirmation_required: formData.get(`confirmation:${action}`) === "true",
      approval_required: formData.get(`approval:${action}`) === "true",
    }));
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/${encodeURIComponent(instanceId)}/policy-drafts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_version_id: requiredValue(formData, "versionId"),
          policies,
        }),
      },
    );
  } catch (error) {
    redirect(
      `/tenants/${tenantId}/capabilities?error=${actionError(error, "agent_spec_stale_write")}`,
    );
  }
  revalidatePath(`/tenants/${tenantId}`);
  redirect(`/tenants/${tenantId}/capabilities?saved=policies`);
}

export async function bindIntegrationOperations(
  formData: FormData,
): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  const instanceId = requiredValue(formData, "instanceId");
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/${encodeURIComponent(instanceId)}/connector-binding-drafts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_version_id: requiredValue(formData, "versionId"),
          connection_id: requiredValue(formData, "connectionId"),
          connector_name: requiredValue(formData, "connectorName"),
          operations: formData
            .getAll("operations")
            .filter((value): value is string => typeof value === "string"),
        }),
      },
    );
  } catch (error) {
    redirect(
      `/tenants/${tenantId}/integrations?error=${actionError(error, "agent_spec_stale_write")}`,
    );
  }
  revalidatePath(`/tenants/${tenantId}`);
  redirect(`/tenants/${tenantId}/integrations?saved=binding`);
}

export async function startIntegrationOAuth(formData: FormData): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  let authorizationUrl: string;
  try {
    const start = await callAuthenticatedBackend<{ authorization_url: string }>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/integrations/oauth/start`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connector_name: requiredValue(formData, "connectorName"),
          scopes: formData
            .getAll("scopes")
            .filter((value): value is string => typeof value === "string"),
        }),
      },
    );
    authorizationUrl = start.authorization_url;
  } catch (error) {
    redirect(`/tenants/${tenantId}/integrations?error=${actionError(error)}`);
  }
  redirect(authorizationUrl);
}

export async function connectWooCommerce(formData: FormData): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/integrations/api-key`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connector_name: "woocommerce",
          credential: JSON.stringify({
            store_url: requiredValue(formData, "storeUrl"),
            consumer_key: requiredValue(formData, "consumerKey"),
            consumer_secret: requiredValue(formData, "consumerSecret"),
            permission: requiredValue(formData, "permission"),
          }),
        }),
      },
    );
  } catch (error) {
    redirect(`/tenants/${tenantId}/integrations?error=${actionError(error)}`);
  }
  revalidatePath(`/tenants/${tenantId}/integrations`);
  redirect(`/tenants/${tenantId}/integrations?saved=connection`);
}

export async function checkIntegrationHealth(
  formData: FormData,
): Promise<void> {
  await integrationConnectionAction(formData, "health");
}

export async function reconnectIntegration(formData: FormData): Promise<void> {
  await integrationConnectionAction(formData, "refresh");
}

export async function revokeIntegration(formData: FormData): Promise<void> {
  await integrationConnectionAction(formData, "revoke");
}

export async function configureApprovalRoute(
  formData: FormData,
): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  const instanceId = requiredValue(formData, "instanceId");
  try {
    const route = await callAuthenticatedBackend<{ revision: number }>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/approvals/routes`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: Number(requiredValue(formData, "routeRevision")),
          configuration: {
            ref: "standard",
            capability: requiredValue(formData, "capability"),
            action: requiredValue(formData, "action"),
            authorized_emails: requiredValue(formData, "emails")
              .split(/[\n,]/)
              .map((value) => value.trim().toLowerCase())
              .filter(Boolean),
            strategy: "first_response",
            enabled: true,
          },
        }),
      },
    );
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/${encodeURIComponent(instanceId)}/approval-route-drafts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_version_id: requiredValue(formData, "versionId"),
          route_revision: route.revision,
        }),
      },
    );
  } catch (error) {
    redirect(
      `/tenants/${tenantId}/capabilities?error=${actionError(error, "agent_spec_stale_write")}`,
    );
  }
  revalidatePath(`/tenants/${tenantId}`);
  redirect(`/tenants/${tenantId}/capabilities?saved=approval`);
}

export async function configureHandoff(formData: FormData): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  const instanceId = requiredValue(formData, "instanceId");
  const enabled = formData.get("enabled") === "true";
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/handoffs/accounts/${encodeURIComponent(requiredValue(formData, "accountId"))}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: Number(requiredValue(formData, "revision")),
          configuration: {
            enabled,
            surface: enabled
              ? {
                  surface: "WHATSAPP_COEXISTENCE",
                  adapter: requiredValue(formData, "surfaceAdapter"),
                  binding_id: requiredValue(formData, "accountId"),
                }
              : null,
            inactivity_hours: Number(
              requiredValue(formData, "inactivityHours"),
            ),
            timezone: requiredValue(formData, "timezone"),
            support_hours: null,
          },
        }),
      },
    );
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/${encodeURIComponent(instanceId)}/human-operations-drafts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_version_id: requiredValue(formData, "versionId"),
          handoff_enabled: enabled,
        }),
      },
    );
  } catch (error) {
    redirect(
      `/tenants/${tenantId}/integrations?error=${actionError(error, "agent_spec_stale_write")}`,
    );
  }
  revalidatePath(`/tenants/${tenantId}`);
  redirect(`/tenants/${tenantId}/integrations?saved=handoff`);
}

export async function createKnowledgeSource(formData: FormData): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  const sourceType = requiredValue(formData, "sourceType");
  let configuration: Record<string, string>;
  if (sourceType === "WEBSITE") {
    configuration = { url: requiredValue(formData, "url") };
  } else if (sourceType === "GOOGLE_DRIVE") {
    configuration = { file_id: requiredValue(formData, "googleDriveFileId") };
  } else if (sourceType === "MANUAL") {
    configuration = {
      title: requiredValue(formData, "name"),
      content: requiredValue(formData, "manualContent"),
    };
  } else {
    redirect(`/tenants/${tenantId}/knowledge?error=source-file`);
  }

  try {
    const source = await callAuthenticatedBackend<{ id: string }>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/knowledge/sources`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: requiredValue(formData, "name"),
          source_type: sourceType,
          authority: requiredValue(formData, "authority"),
          configuration,
        }),
      },
    );
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/knowledge/sources/${encodeURIComponent(source.id)}/ingestions`,
      { method: "POST" },
    );
  } catch (error) {
    redirect(`/tenants/${tenantId}/knowledge?error=${actionError(error)}`);
  }
  revalidatePath(`/tenants/${tenantId}/knowledge`);
  redirect(`/tenants/${tenantId}/knowledge?saved=source`);
}

type KnowledgeUploadSourceInput = {
  tenantId: string;
  name: string;
  sourceType: "PDF" | "DOCX" | "SPREADSHEET";
  authority: "AUTHORITATIVE" | "SECONDARY" | "REFERENCE";
};

type KnowledgeUploadSource = {
  sourceId: string;
  uploadKey: string;
  mediaType: string;
};

export async function createKnowledgeUploadSource(
  input: KnowledgeUploadSourceInput,
): Promise<ActionResult<KnowledgeUploadSource>> {
  const definitions = {
    PDF: { extension: ".pdf", mediaType: "application/pdf" },
    DOCX: {
      extension: ".docx",
      mediaType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    SPREADSHEET: {
      extension: ".xlsx",
      mediaType:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
  } as const;
  const definition = definitions[input.sourceType];
  const uploadKey = `${randomUUID()}${definition.extension}`;
  try {
    const source = await callAuthenticatedBackend<{ id: string }>(
      `/admin/tenants/${encodeURIComponent(input.tenantId)}/knowledge/sources`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: input.name.trim(),
          source_type: input.sourceType,
          authority: input.authority,
          configuration: { upload_key: uploadKey },
        }),
      },
    );
    return {
      ok: true,
      data: {
        sourceId: source.id,
        uploadKey,
        mediaType: definition.mediaType,
      },
    };
  } catch {
    return { ok: false, message: "The source record could not be created." };
  }
}

export async function startKnowledgeSourceIngestion(input: {
  tenantId: string;
  sourceId: string;
}): Promise<ActionResult> {
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(input.tenantId)}/knowledge/sources/${encodeURIComponent(input.sourceId)}/ingestions`,
      { method: "POST" },
    );
    revalidatePath(`/tenants/${input.tenantId}/knowledge`);
    return { ok: true, data: undefined };
  } catch {
    return {
      ok: false,
      message: "The source was uploaded but synchronization could not start.",
    };
  }
}

export async function syncKnowledgeSource(formData: FormData): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/knowledge/sources/${encodeURIComponent(requiredValue(formData, "sourceId"))}/ingestions`,
      { method: "POST" },
    );
  } catch (error) {
    redirect(`/tenants/${tenantId}/knowledge?error=${actionError(error)}`);
  }
  revalidatePath(`/tenants/${tenantId}/knowledge`);
  redirect(`/tenants/${tenantId}/knowledge?saved=sync`);
}

export async function reviewKnowledgeProposal(
  formData: FormData,
): Promise<void> {
  const tenantId = requiredValue(formData, "tenantId");
  const proposalId = requiredValue(formData, "proposalId");
  const decision = requiredValue(formData, "decision");
  let editedPayload: Record<string, unknown> | undefined;
  try {
    if (decision === "EDIT") {
      editedPayload = {
        source_id: requiredValue(formData, "sourceId"),
        authority: requiredValue(formData, "authority"),
        locator: JSON.parse(requiredValue(formData, "locator")),
        content_digest: requiredValue(formData, "contentDigest"),
      };
      if (requiredValue(formData, "artifactType") === "FACT") {
        Object.assign(editedPayload, {
          key: requiredValue(formData, "factKey"),
          kind: requiredValue(formData, "factKind"),
          value: JSON.parse(requiredValue(formData, "factValue")),
        });
      } else {
        Object.assign(editedPayload, {
          category: requiredValue(formData, "documentCategory"),
          title: requiredValue(formData, "documentTitle"),
          text: requiredValue(formData, "documentText"),
        });
      }
    }
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/knowledge/proposals/${encodeURIComponent(proposalId)}/review`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision: Number(requiredValue(formData, "revision")),
          decision,
          edited_payload: editedPayload,
        }),
      },
    );
  } catch (error) {
    redirect(`/tenants/${tenantId}/knowledge?error=${actionError(error)}`);
  }
  revalidatePath(`/tenants/${tenantId}/knowledge`);
  redirect(`/tenants/${tenantId}/knowledge?saved=review`);
}

export async function prepareKnowledgeEmbeddings(
  formData: FormData,
): Promise<void> {
  await knowledgeVersionAction(formData, "embeddings", "embeddings");
}

export async function promoteKnowledgeToTest(
  formData: FormData,
): Promise<void> {
  await knowledgeVersionAction(formData, "test-v0", "test");
}

async function knowledgeVersionAction(
  formData: FormData,
  action: "embeddings" | "test-v0",
  saved: string,
): Promise<never> {
  const tenantId = requiredValue(formData, "tenantId");
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/knowledge/versions/${encodeURIComponent(requiredValue(formData, "versionId"))}/${action}`,
      { method: "POST" },
    );
  } catch (error) {
    redirect(`/tenants/${tenantId}/knowledge?error=${actionError(error)}`);
  }
  revalidatePath(`/tenants/${tenantId}/knowledge`);
  redirect(`/tenants/${tenantId}/knowledge?saved=${saved}`);
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

async function integrationConnectionAction(
  formData: FormData,
  action: "health" | "refresh" | "revoke",
): Promise<never> {
  const tenantId = requiredValue(formData, "tenantId");
  try {
    await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/integrations/connections/${encodeURIComponent(requiredValue(formData, "connectionId"))}/${action}`,
      { method: "POST" },
    );
  } catch (error) {
    redirect(`/tenants/${tenantId}/integrations?error=${actionError(error)}`);
  }
  revalidatePath(`/tenants/${tenantId}`);
  redirect(`/tenants/${tenantId}/integrations?saved=${action}`);
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
