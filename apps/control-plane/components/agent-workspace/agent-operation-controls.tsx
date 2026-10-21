"use client";

import { useActionState, useEffect, useRef } from "react";
import type {
  AgentOperationView,
  OperationActionState,
} from "../../lib/agent-operations";
import { operationAction } from "./operation-actions";

const idle: OperationActionState = { status: "idle" };

function changedAt(value: string): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("es-CO", {
      timeZone: "America/Bogota",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      numberingSystem: "latn",
    })
      .formatToParts(new Date(value))
      .map((part) => [part.type, part.value]),
  );
  return `${parts.day}/${parts.month}/${parts.year} ${parts.hour}:${parts.minute} (Bogotá)`;
}

export function AgentOperationControls({
  tenantId,
  agentId,
  initial,
}: {
  tenantId: string;
  agentId: string;
  initial: AgentOperationView | null;
}) {
  const [result, action, pending] = useActionState(operationAction, idle);
  const confirmation = useRef<HTMLDetailsElement>(null);
  const operation =
    result.operation &&
    (!initial || result.operation.revision >= initial.revision)
      ? result.operation
      : initial;
  const available =
    operation?.controls_available === true &&
    initial?.controls_available !== false;

  useEffect(() => {
    if (result.status === "success" && confirmation.current) {
      confirmation.current.open = false;
      confirmation.current.querySelector("summary")?.focus();
    }
  }, [result]);

  function closeConfirmation() {
    if (confirmation.current) {
      confirmation.current.open = false;
      confirmation.current.querySelector("summary")?.focus();
    }
  }

  return (
    <section className="workspace-card" aria-label="Operación del agente">
      <h2>Operación del agente</h2>
      <p>
        {operation
          ? operation.enabled
            ? "Respuestas automáticas habilitadas"
            : "Respuestas automáticas pausadas"
          : "Estado operativo sin verificar"}
      </p>
      {operation ? (
        <p className="workspace-muted">
          Último cambio:{" "}
          <time dateTime={operation.updated_at}>
            {changedAt(operation.updated_at)}
          </time>
        </p>
      ) : null}
      <p className="workspace-muted">
        Pausar no desconecta WhatsApp ni modifica la versión publicada.
      </p>
      {available && operation && !result.requiresRefresh ? (
        <form action={action}>
          <input type="hidden" name="tenantId" value={tenantId} />
          <input type="hidden" name="agentId" value={agentId} />
          <input type="hidden" name="revision" value={operation.revision} />
          <input
            type="hidden"
            name="command"
            value={operation.enabled ? "pause" : "resume"}
          />
          <details ref={confirmation}>
            <summary className="workspace-secondary">
              {operation.enabled ? "Pausar agente" : "Reactivar agente"}
            </summary>
            <p>
              {operation.enabled
                ? "Se guardarán los mensajes sin respuesta automática. Un envío ya iniciado podría llegar. Las respuestas pendientes no se enviarán al reactivar."
                : "Solo responderá mensajes nuevos. No responderá automáticamente los recibidos antes o durante la pausa."}
            </p>
            <button
              className="workspace-primary"
              name="confirmOperation"
              value="yes"
              disabled={pending}
            >
              {pending
                ? "Guardando estado…"
                : operation.enabled
                  ? "Confirmar pausa"
                  : "Confirmar reactivación"}
            </button>{" "}
            <button
              type="button"
              className="workspace-secondary"
              disabled={pending}
              onClick={closeConfirmation}
            >
              Cancelar
            </button>
          </details>
        </form>
      ) : (
        <p className="workspace-muted">
          {result.requiresRefresh
            ? "Consulta el estado antes de realizar otro cambio."
            : "Control no disponible hasta verificar la instalación compatible."}
        </p>
      )}
      {pending ? <p role="status">Guardando estado…</p> : null}
      {result.message ? (
        <p
          role={
            result.status === "error" || result.status === "conflict"
              ? "alert"
              : "status"
          }
        >
          {result.message}
        </p>
      ) : null}
      <form action={action}>
        <input type="hidden" name="tenantId" value={tenantId} />
        <input type="hidden" name="agentId" value={agentId} />
        <input type="hidden" name="command" value="refresh" />
        <button className="workspace-secondary" disabled={pending}>
          Recargar estado
        </button>
      </form>
    </section>
  );
}
