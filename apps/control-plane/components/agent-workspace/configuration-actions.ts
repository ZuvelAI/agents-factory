"use server";

import { revalidatePath } from "next/cache";
import { BackendProblem, callAuthenticatedBackend } from "../../lib/api";
import {
  configurationPath,
  parseDraft,
  parseProfile,
  readConfiguration,
  readProfile,
} from "../../lib/agent-configuration";
import type { ConfigurationActionState } from "../../lib/agent-configuration";
import { isWorkspaceId } from "../../lib/agent-workspace";

function input(form: FormData, name: string, max = 200): string {
  const value = form.get(name);
  if (typeof value !== "string" || value.length > max)
    throw new Error("invalid_input");
  return value;
}
function number(form: FormData, name: string, min = 1): number {
  const raw = input(form, name, 16),
    value = Number(raw);
  if (!/^\d+$/.test(raw) || !Number.isSafeInteger(value) || value < min)
    throw new Error("invalid_revision");
  return value;
}
function failure(error: unknown, submitted?: string): ConfigurationActionState {
  if (error instanceof BackendProblem && error.status === 409)
    return {
      status: "conflict",
      message:
        "Hay cambios más recientes. Tu texto se conserva; compara antes de volver a guardar.",
      submitted,
    };
  return {
    status:
      error instanceof BackendProblem && error.status === 422
        ? "validation"
        : "error",
    message:
      "No pudimos guardar. Revisa los campos e intenta de nuevo; tu texto se conserva.",
    submitted,
  };
}
function changed(tenant: string, agent?: string) {
  revalidatePath("/tenants");
  revalidatePath(`/tenants/${tenant}`);
  if (agent) revalidatePath(`/tenants/${tenant}/agents/${agent}`);
}
export async function saveAgentConfiguration(
  _previous: ConfigurationActionState,
  form: FormData,
): Promise<ConfigurationActionState> {
  let submitted: string | undefined;
  try {
    const tenant = input(form, "tenantId"),
      agent = input(form, "agentId");
    const path = configurationPath(tenant, agent);
    submitted = input(form, "configuration", 100000);
    const configuration = JSON.parse(submitted);
    for (const [section, key] of [
      ["agent", "supported_languages"],
      ["approval_routes", "approver_emails"],
    ]) {
      if (Array.isArray(configuration?.[section]?.[key]))
        configuration[section][key] = configuration[section][key]
          .map((item: unknown) =>
            typeof item === "string" ? item.trim() : item,
          )
          .filter((item: unknown) => item !== "");
    }
    const draft = parseDraft(
      await callAuthenticatedBackend(path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: number(form, "revision"),
          configuration,
        }),
      }),
    );
    changed(tenant, agent);
    return {
      status: "success",
      message: "Borrador guardado. El agente publicado no cambió.",
      draft,
    };
  } catch (error) {
    return failure(error, submitted);
  }
}
export async function compareAgentConfiguration(
  tenant: string,
  agent: string,
): Promise<ConfigurationActionState> {
  try {
    return { status: "success", draft: await readConfiguration(tenant, agent) };
  } catch (error) {
    return failure(error);
  }
}
export async function refreshAgentCompany(
  _previous: ConfigurationActionState,
  form: FormData,
): Promise<ConfigurationActionState> {
  try {
    if (form.get("confirm") !== "on") throw new Error("confirmation_required");
    const tenant = input(form, "tenantId"),
      agent = input(form, "agentId");
    const draft = parseDraft(
      await callAuthenticatedBackend(
        configurationPath(tenant, agent) + "/refresh-company",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision: number(form, "revision"),
            expected_company_revision: number(form, "companyRevision"),
          }),
        },
      ),
    );
    changed(tenant, agent);
    return {
      status: "success",
      message: "Datos de empresa incorporados al borrador.",
      draft,
    };
  } catch (error) {
    return failure(error);
  }
}
export async function saveCompanyProfile(
  _previous: ConfigurationActionState,
  form: FormData,
): Promise<ConfigurationActionState> {
  let submitted: string | undefined;
  try {
    const tenant = input(form, "tenantId");
    submitted = input(form, "configuration", 20000);
    const profile = parseProfile(
      await callAuthenticatedBackend(configurationPath(tenant), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: number(form, "revision", 0),
          configuration: JSON.parse(submitted),
        }),
      }),
    );
    changed(tenant);
    return {
      status: "success",
      message:
        "Datos compartidos guardados. Los agentes existentes no cambiaron.",
      profile,
    };
  } catch (error) {
    return failure(error, submitted);
  }
}
export async function compareCompanyProfile(
  tenant: string,
): Promise<ConfigurationActionState> {
  try {
    return { status: "success", profile: await readProfile(tenant) };
  } catch (error) {
    return failure(error);
  }
}
export async function createConfigurationEntity(
  _previous: ConfigurationActionState,
  form: FormData,
): Promise<ConfigurationActionState> {
  try {
    const tenant = input(form, "tenantId"),
      name = input(form, "name");
    if (tenant && !isWorkspaceId(tenant)) throw new Error("invalid_id");
    const result = await callAuthenticatedBackend(
      `/admin/agent-workspace/companies${tenant ? `/${tenant}/agents` : ""}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          tenant ? { name } : { name, slug: input(form, "slug", 100) },
        ),
      },
    );
    const href = tenant
      ? `/tenants/${tenant}/agents/${parseDraft(result).agent_instance_id}/edit`
      : `/tenants/${parseProfile(result).tenant_id}`;
    revalidatePath("/tenants");
    return {
      status: "success",
      message: "Espacio creado sin conectar ni publicar WhatsApp.",
      href,
    };
  } catch (error) {
    return failure(error);
  }
}
export async function importLegacyConfiguration(
  _previous: ConfigurationActionState,
  form: FormData,
): Promise<ConfigurationActionState> {
  try {
    if (form.get("confirm") !== "on") throw new Error("confirmation_required");
    const tenant = input(form, "tenantId"),
      agent = input(form, "agentId");
    const draft = parseDraft(
      await callAuthenticatedBackend(
        configurationPath(tenant, agent) + "/import-legacy",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_legacy_revision: number(form, "legacyRevision"),
            expected_company_revision: number(form, "companyRevision", 0),
          }),
        },
      ),
    );
    changed(tenant, agent);
    return {
      status: "success",
      draft,
      message:
        "Configuración importada. La conexión y la versión activa no cambiaron.",
    };
  } catch (error) {
    return failure(error);
  }
}
