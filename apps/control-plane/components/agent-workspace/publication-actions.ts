"use server";
import { revalidatePath } from "next/cache";
import { BackendProblem, callAuthenticatedBackend } from "../../lib/api";
import {
  publicationPath,
  readPublication,
  parsePublicationRun,
} from "../../lib/workspace-publication";
import type {
  PublicationActionState,
  PublicationState,
} from "../../lib/workspace-publication";
import { isWorkspaceId } from "../../lib/agent-workspace";
function field(form: FormData, key: string, max = 200) {
  const v = form.get(key);
  if (typeof v !== "string" || v.length > max) throw new Error("invalid_input");
  return v;
}
function id(form: FormData, key: string) {
  const v = field(form, key);
  if (!isWorkspaceId(v)) throw new Error("invalid_input");
  return v;
}
function rev(form: FormData, key: string, min = 1) {
  const v = field(form, key, 16);
  if (!/^\d+$/.test(v) || !Number.isSafeInteger(Number(v)) || Number(v) < min)
    throw new Error("invalid_input");
  return Number(v);
}
async function focusedState(
  tenant: string,
  agent: string,
  cursor: string | undefined,
  section: string,
  runs: string[],
): Promise<PublicationState> {
  const state = await readPublication(tenant, agent, cursor, section);
  if (runs.length > 2 || runs.some((run) => !isWorkspaceId(run)))
    throw new Error("invalid_input");
  for (const runId of new Set(runs)) {
    if (state.runs.some((run) => run.id === runId)) continue;
    const run = parsePublicationRun(
      await callAuthenticatedBackend(
        `${publicationPath(tenant, agent)}/tests/${runId}`,
      ),
    );
    if (run.agent_instance_id !== agent || run.id !== runId)
      throw new Error("invalid_input");
    state.runs.unshift(run);
  }
  return state;
}
export async function publicationAction(
  _previous: PublicationActionState,
  form: FormData,
): Promise<PublicationActionState> {
  try {
    const tenant = id(form, "tenantId"),
      agent = id(form, "agentId"),
      command = field(form, "command"),
      root = publicationPath(tenant, agent);
    let suffix = "",
      payload: Record<string, unknown> = {},
      message = "Estado actualizado";
    if (command === "prepare") {
      suffix = "/candidates";
      payload = {
        expected_revision: rev(form, "revision"),
        expected_company_revision: rev(form, "companyRevision"),
      };
      message = "Versión de prueba preparada. WhatsApp no cambió.";
    } else if (command === "test" || command === "preview") {
      suffix = `/candidates/${id(form, "versionId")}/${command === "test" ? "tests" : "preview"}`;
      payload = {
        expected_revision: rev(form, "revision"),
        request_key: id(form, "requestKey"),
      };
      if (command === "preview") {
        const messages: unknown = JSON.parse(field(form, "messages", 50000));
        if (
          !Array.isArray(messages) ||
          messages.length < 1 ||
          messages.length > 20
        )
          throw new Error("invalid_input");
        payload.messages = messages;
      }
      message = "Prueba solicitada. Su resultado no modifica WhatsApp.";
    } else if (command === "review") {
      const decision = field(form, "decision");
      if (!["approve", "reject"].includes(decision))
        throw new Error("invalid_input");
      if (decision === "approve" && form.get("confirmReview") !== "on")
        return {
          status: "validation",
          message: "Confirma que revisaste las respuestas exactas.",
        };
      suffix = `/tests/${id(form, "runId")}/review`;
      payload = {
        expected_revision: rev(form, "revision"),
        approved: decision === "approve",
        confirm_review: form.get("confirmReview") === "on",
      };
      message = "Revisión registrada. Todavía no se ha publicado.";
    } else if (command === "publish") {
      if (form.get("confirmPublish") !== "on")
        return {
          status: "validation",
          message: "Confirma la versión y el número destino.",
        };
      const current = field(form, "currentAgent");
      if (current && !isWorkspaceId(current)) throw new Error("invalid_input");
      suffix = "/publish";
      payload = {
        expected_revision: rev(form, "revision"),
        version_id: id(form, "versionId"),
        test_run_id: id(form, "runId"),
        whatsapp_account_id: id(form, "accountId"),
        expected_binding_revision: rev(form, "bindingRevision", 0),
        expected_current_agent_id: current || null,
        confirm_publish: true,
      };
      message = "Publicación confirmada en el número seleccionado.";
    } else if (command === "rollback") {
      if (form.get("confirmRollback") !== "on")
        return {
          status: "validation",
          message: "Confirma la versión que quieres recuperar.",
        };
      suffix = "/rollback";
      payload = {
        whatsapp_account_id: id(form, "accountId"),
        target_version_id: id(form, "versionId"),
        expected_binding_revision: rev(form, "bindingRevision"),
        confirm_rollback: true,
      };
      message = "Versión anterior recuperada. Tu borrador se conserva.";
    } else if (command !== "refresh") throw new Error("invalid_input");
    let run;
    if (command !== "refresh") {
      const result = await callAuthenticatedBackend(root + suffix, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (["test", "preview", "review"].includes(command))
        run = parsePublicationRun(result);
    }
    let state;
    try {
      state = await focusedState(
        tenant,
        agent,
        String(form.get("pageCursor") ?? "") || undefined,
        String(form.get("pageSection") ?? "candidates"),
        [form.get("focusedSuite"), form.get("focusedPreview")].filter(
          (value): value is string =>
            typeof value === "string" && value.length > 0,
        ),
      );
    } catch {
      // A successful write is not undone by an unavailable read projection.
      return {
        status: "success",
        message: `${message} No se pudo refrescar el estado; consulta sin repetir la operación.`,
        run,
      };
    }
    revalidatePath(`/tenants/${tenant}/agents/${agent}`);
    revalidatePath(`/tenants/${tenant}`);
    return { status: "success", message, state, run };
  } catch (error) {
    if (error instanceof BackendProblem && error.status === 409)
      return {
        status: "conflict",
        message:
          "La revisión, asignación o prueba cambió. Tu texto se conserva; consulta el estado antes de intentar de nuevo.",
      };
    if (error instanceof BackendProblem && error.status === 429)
      return {
        status: "error",
        message:
          "Se alcanzó el límite de pruebas por hora. Espera antes de volver a solicitar.",
      };
    return {
      status: "error",
      message:
        "No se pudo confirmar la operación. Tu texto se conserva. Consulta el estado; no repitas una publicación a ciegas.",
    };
  }
}
export async function refreshPublication(
  tenant: string,
  agent: string,
  cursor?: string,
  section = "candidates",
  runIds: string[] = [],
): Promise<PublicationActionState> {
  try {
    return {
      status: "success",
      state: await focusedState(tenant, agent, cursor, section, runIds),
    };
  } catch {
    return {
      status: "error",
      message: "No se pudo consultar el estado. No se inició otra prueba.",
    };
  }
}
