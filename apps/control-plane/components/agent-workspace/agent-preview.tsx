"use client";
import { useActionState, useState } from "react";
import { publicationAction } from "./publication-actions";
import { useUnsavedConfiguration } from "./use-unsaved-configuration";
import type {
  PublicationActionState,
  PublicationState,
  Run,
  PreviewMessage,
} from "../../lib/workspace-publication";

export function AgentPreview({
  tenant,
  agent,
  versionId,
  revision,
  run,
  onState,
  onDirty,
}: {
  tenant: string;
  agent: string;
  versionId: string;
  revision: number;
  run: Run | undefined;
  onState: (state: PublicationState) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [result, action, pending] = useActionState(
    async (previous: PublicationActionState, form: FormData) => {
      form.set("requestKey", crypto.randomUUID());
      const response = await publicationAction(previous, form);
      if (response.state) onState(response.state);
      if (response.run) {
        setText("");
        onDirty(false);
      }
      return response;
    },
    { status: "idle" },
  );
  useUnsavedConfiguration(text.trim().length > 0);
  const previewResult =
    run?.result && "response" in run.result ? run.result : null;
  const history: PreviewMessage[] = [
    ...(run?.input_messages ?? []),
    ...(previewResult?.response
      ? [{ role: "assistant" as const, text: previewResult.response }]
      : []),
  ];
  const waiting = run?.result === null && run.is_current;
  return (
    <article className="workspace-card">
      <h2>Conversación de prueba</h2>
      <p className="workspace-muted">
        Prueba aislada · no envía WhatsApp · consume API. Herramientas
        deshabilitadas; no comprueba integraciones externas. No pegues secretos
        ni datos personales.
      </p>
      <div className="preview-messages" aria-label="Mensajes de la prueba">
        {history.map((message, index) => (
          <p
            key={`${run?.id}-${index}`}
            className={
              message.role === "user" ? "preview-user" : "preview-agent"
            }
          >
            <strong>{message.role === "user" ? "Tú" : "Agente"}</strong>
            <br />
            {message.text}
          </p>
        ))}
      </div>
      {previewResult?.error_code && (
        <p role="alert">
          La prueba falló; no se generó una respuesta de respaldo.
        </p>
      )}
      {waiting && (
        <p role="status">
          Prueba pendiente. Consulta el estado; no es necesario enviarla otra
          vez.
        </p>
      )}
      <form action={action}>
        <input type="hidden" name="tenantId" value={tenant} />
        <input type="hidden" name="agentId" value={agent} />
        <input type="hidden" name="revision" value={revision} />
        <input type="hidden" name="versionId" value={versionId} />
        <input type="hidden" name="command" value="preview" />
        <input
          type="hidden"
          name="messages"
          value={JSON.stringify([
            ...(previewResult?.response ? history.slice(-18) : []),
            { role: "user", text },
          ])}
        />
        <label>
          Mensaje de prueba
          <textarea
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              onDirty(event.target.value.trim().length > 0);
            }}
            maxLength={2000}
            rows={3}
            disabled={pending || waiting}
          />
        </label>
        <p className="workspace-muted">
          Se incluyen hasta nueve turnos anteriores de esta prueba. Cambiar de
          candidato inicia otra conversación.
        </p>
        <button disabled={pending || waiting || !text.trim()}>
          Enviar prueba aislada
        </button>
        {result.message && (
          <p role={result.status === "success" ? "status" : "alert"}>
            {result.message}
          </p>
        )}
      </form>
    </article>
  );
}
