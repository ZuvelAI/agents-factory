"use server";
import { revalidatePath } from "next/cache";
import { BackendProblem } from "../../lib/api";
import {
  readAgentOperation,
  setAgentOperation,
} from "../../lib/agent-operations";
import type { OperationActionState } from "../../lib/agent-operations";
import { isWorkspaceId } from "../../lib/agent-workspace";

export async function operationAction(
  _previous: OperationActionState,
  form: FormData,
): Promise<OperationActionState> {
  const tenant = form.get("tenantId"),
    agent = form.get("agentId"),
    command = form.get("command");
  if (
    typeof tenant !== "string" ||
    !isWorkspaceId(tenant) ||
    typeof agent !== "string" ||
    !isWorkspaceId(agent) ||
    !["pause", "resume", "refresh"].includes(String(command))
  )
    return { status: "validation", message: "Solicitud no válida." };
  if (command !== "refresh" && form.get("confirmOperation") !== "yes")
    return {
      status: "validation",
      message: "Confirma el cambio del estado del agente.",
    };
  const revision = String(form.get("revision") ?? "");
  if (
    command !== "refresh" &&
    (!/^\d{1,16}$/.test(revision) ||
      !Number.isSafeInteger(Number(revision)) ||
      Number(revision) < 1)
  )
    return {
      status: "validation",
      message: "Recarga el estado antes de continuar.",
    };
  try {
    const operation =
      command === "refresh"
        ? await readAgentOperation(tenant, agent)
        : await setAgentOperation(
            tenant,
            agent,
            command === "resume",
            Number(revision),
          );
    revalidatePath(`/tenants/${tenant}/agents/${agent}`);
    revalidatePath(`/tenants/${tenant}`);
    revalidatePath("/tenants");
    revalidatePath("/");
    return {
      status: "success",
      operation,
      message:
        command === "pause"
          ? "Agente pausado. Los mensajes se conservarán sin respuesta automática."
          : command === "resume"
            ? "Agente reactivado. Solo responderá mensajes nuevos."
            : "Estado actualizado.",
    };
  } catch (error) {
    if (error instanceof BackendProblem && error.status === 409)
      return {
        status: "conflict",
        requiresRefresh: true,
        message: "El estado cambió. Recarga antes de intentar nuevamente.",
      };
    return {
      status: "error",
      requiresRefresh: true,
      message:
        "No pudimos confirmar el estado. Recarga antes de intentarlo de nuevo.",
    };
  }
}
