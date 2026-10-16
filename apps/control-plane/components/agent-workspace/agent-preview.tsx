"use client";
import { useActionState, useRef, useState } from "react";
import {
  previewInput,
  requestIdentity,
  type RequestIdentity,
} from "../../lib/publication-preview-input";
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
  cursor,
  section,
  suiteId,
  onRun,
}: {
  tenant: string;
  agent: string;
  versionId: string;
  revision: number;
  run: Run | undefined;
  onState: (state: PublicationState) => void;
  onDirty: (dirty: boolean) => void;
  cursor?: string;
  section: string;
  suiteId?: string;
  onRun: (run: Run) => void;
}) {
  const [text, setText] = useState("");
  const [reset, setReset] = useState(false);
  const identity = useRef<RequestIdentity | null>(null);
  const submittedMessages = useRef("");
  const [result, action, pending] = useActionState(
    async (previous: PublicationActionState, form: FormData) => {
      const signature = JSON.stringify([versionId, revision, text, reset]);
      if (identity.current?.signature !== signature)
        submittedMessages.current = String(form.get("messages"));
      identity.current = requestIdentity(identity.current, signature);
      form.set("messages", submittedMessages.current);
      form.set("requestKey", identity.current.key);
      const response = await publicationAction(previous, form);
      if (response.state) onState(response.state);
      if (response.run) {
        onRun(response.run);
        identity.current = null;
        setReset(false);
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
  const history: PreviewMessage[] = reset
    ? []
    : [
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
        <input type="hidden" name="pageCursor" value={cursor ?? ""} />
        <input type="hidden" name="pageSection" value={section} />
        <input type="hidden" name="focusedSuite" value={suiteId ?? ""} />
        <input type="hidden" name="tenantId" value={tenant} />
        <input type="hidden" name="agentId" value={agent} />
        <input type="hidden" name="revision" value={revision} />
        <input type="hidden" name="versionId" value={versionId} />
        <input type="hidden" name="command" value="preview" />
        <input
          type="hidden"
          name="messages"
          value={JSON.stringify(
            previewInput(previewResult?.response ? history : [], text),
          )}
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
          Se conservan hasta nueve turnos completos recientes, dentro de 20000
          caracteres; los más antiguos quedan fuera del siguiente envío. Cambiar
          de candidato inicia otra conversación.
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
      <button
        type="button"
        disabled={pending || waiting}
        onClick={() => {
          if (
            text.trim() &&
            !window.confirm(
              "¿Descartar el mensaje sin enviar e iniciar otra conversación de prueba?",
            )
          )
            return;
          setReset(true);
          setText("");
          onDirty(false);
          identity.current = null;
        }}
      >
        Iniciar otra conversación de prueba
      </button>
    </article>
  );
}
