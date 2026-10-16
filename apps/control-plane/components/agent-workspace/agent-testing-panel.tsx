"use client";
import Link from "next/link";
import { useActionState, useEffect, useRef, useState } from "react";
import { publicationAction, refreshPublication } from "./publication-actions";
import { AgentPreview } from "./agent-preview";
import { AgentPublicationConfirmation } from "./agent-publication-confirmation";
import type {
  PublicationActionState,
  PublicationState,
} from "../../lib/workspace-publication";

export function AgentTestingPanel({
  tenant,
  agent,
  initial,
}: {
  tenant: string;
  agent: string;
  initial: PublicationState;
}) {
  const [state, setState] = useState(initial);
  const [selected, setSelected] = useState("");
  const [previewDirty, setPreviewDirty] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const [result, action, pending] = useActionState(
    async (previous: PublicationActionState, form: FormData) => {
      if (form.get("command") === "test")
        form.set("requestKey", crypto.randomUUID());
      const response = await publicationAction(previous, form);
      if (response.state) setState(response.state);
      return response;
    },
    { status: "idle" },
  );
  const pollingStarted = useRef(0);
  const waiting = state.runs.some(
    (run) => run.is_current && run.result === null,
  );
  useEffect(() => {
    if (!waiting) {
      pollingStarted.current = 0;
      return;
    }
    if (!pollingStarted.current) pollingStarted.current = Date.now();
    let active = true,
      busy = false;
    const timer = setInterval(async () => {
      if (
        !active ||
        busy ||
        document.visibilityState !== "visible" ||
        Date.now() - pollingStarted.current >= 120000
      )
        return;
      busy = true;
      const response = await refreshPublication(tenant, agent);
      busy = false;
      if (active && response.state) setState(response.state);
      if (active && response.status === "error")
        setRefreshError(response.message ?? "No se pudo consultar el estado.");
    }, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [tenant, agent, waiting]);
  const candidate = state.candidates.find((c) => c.version.id === selected);
  const suite = state.runs.find(
    (run) => run.version_id === selected && run.run_kind === "SCENARIOS",
  );
  const preview = state.runs.find(
    (run) => run.version_id === selected && run.run_kind === "PREVIEW",
  );
  const scope = (
    <>
      <input type="hidden" name="tenantId" value={tenant} />
      <input type="hidden" name="agentId" value={agent} />
      <input type="hidden" name="revision" value={state.draft_revision} />
      <input
        type="hidden"
        name="companyRevision"
        value={state.company_revision}
      />
      <input type="hidden" name="versionId" value={selected} />
    </>
  );
  return (
    <section className="workspace configuration-editor publication-panel">
      <Link
        className="workspace-back"
        href={`/tenants/${tenant}/agents/${agent}/edit`}
      >
        ← Editar borrador
      </Link>
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Revisión antes de publicar</p>
          <h1>Probar y publicar</h1>
          <p>
            Borrador guardado: revisión {state.draft_revision}. Preparar, probar
            y aprobar no cambian WhatsApp.
          </p>
        </div>
        <span className="workspace-badge">Sin publicación automática</span>
      </header>
      {result.message && (
        <p role={result.status === "success" ? "status" : "alert"}>
          {result.message}
        </p>
      )}
      {refreshError && <p role="alert">{refreshError}</p>}
      <article className="workspace-card">
        <h2>1. Preparar revisión guardada</h2>
        {state.blockers.length > 0 && (
          <ul>
            {state.blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        )}
        <form action={action}>
          {scope}
          <input type="hidden" name="command" value="prepare" />
          <button disabled={pending || state.blockers.length > 0}>
            Preparar versión de prueba
          </button>
        </form>
        <label>
          Versión para probar
          <select
            value={selected}
            disabled={pending}
            onChange={(event) => {
              if (
                previewDirty &&
                !window.confirm(
                  "Hay un mensaje de prueba sin enviar. ¿Quieres descartarlo y cambiar de versión?",
                )
              )
                return;
              setPreviewDirty(false);
              setSelected(event.target.value);
              setRefreshError("");
            }}
          >
            <option value="">Selecciona una versión exacta</option>
            {state.candidates.map((c) => (
              <option key={c.version.id} value={c.version.id}>
                Versión {c.version.version_number} · borrador {c.revision} ·{" "}
                {c.version.model}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={pending}
          onClick={async () => {
            const response = await refreshPublication(tenant, agent);
            if (response.state) {
              setState(response.state);
              setRefreshError("");
            } else setRefreshError(response.message ?? "Estado no disponible");
          }}
        >
          Consultar estado
        </button>
      </article>
      {candidate && (
        <>
          <AgentPreview
            key={selected}
            tenant={tenant}
            agent={agent}
            versionId={selected}
            revision={candidate.revision}
            run={preview}
            onState={setState}
            onDirty={setPreviewDirty}
          />
          <article className="workspace-card">
            <h2>2. Escenarios y revisión humana</h2>
            <p>
              Esta batería realiza cinco llamadas al modelo y un control humano
              local. Revisa información, tono, precios desconocidos, alcance y
              protección de instrucciones. Los chequeos técnicos no certifican
              por sí solos la calidad de las respuestas.
            </p>
            <form action={action}>
              {scope}
              <input type="hidden" name="command" value="test" />
              <button
                disabled={
                  pending ||
                  (suite?.result === null && suite.is_current) ||
                  candidate.revision !== state.draft_revision
                }
              >
                Ejecutar escenarios
              </button>
            </form>
            {suite && (
              <>
                <p>
                  {suite.is_current
                    ? "Prueba vigente"
                    : "Prueba obsoleta o vencida; prepara nuevas pruebas"}{" "}
                  · {suite.result ? "Resultado disponible" : "Pendiente"}
                </p>
                {suite.result &&
                  "scenarios" in suite.result &&
                  suite.result.scenarios.map((s) => (
                    <details key={s.key} className="workspace-sections">
                      <summary>
                        {s.key} ·{" "}
                        {s.passed
                          ? "Chequeo técnico completado"
                          : "Requiere revisión"}
                      </summary>
                      <p>{s.prompt}</p>
                      <p>{s.response ?? "Sin respuesta"}</p>
                      {s.error_code && <p role="alert">La generación falló.</p>}
                    </details>
                  ))}
                {suite.approved === null &&
                  suite.result &&
                  "checks_passed" in suite.result && (
                    <form action={action}>
                      {scope}
                      <input type="hidden" name="command" value="review" />
                      <input type="hidden" name="runId" value={suite.id} />
                      <label>
                        <input
                          name="confirmReview"
                          type="checkbox"
                          required
                          disabled={pending || !suite.is_current}
                        />{" "}
                        He revisado las respuestas exactas
                      </label>
                      <button
                        name="decision"
                        value="approve"
                        disabled={
                          pending ||
                          !suite.is_current ||
                          !suite.result.checks_passed
                        }
                      >
                        Aprobar escenarios
                      </button>
                      <button
                        name="decision"
                        value="reject"
                        formNoValidate
                        disabled={pending || !suite.is_current}
                      >
                        Rechazar escenarios
                      </button>
                    </form>
                  )}
                {suite.approved !== null && (
                  <p>
                    Decisión: {suite.approved ? "Aprobada" : "Rechazada"}. La
                    revisión no publica automáticamente.
                  </p>
                )}
              </>
            )}
          </article>
          <AgentPublicationConfirmation
            key={`${selected}:${suite?.id}:${state.accounts.map((a) => a.binding?.revision ?? 0).join("-")}`}
            tenant={tenant}
            agent={agent}
            state={state}
            candidate={candidate}
            run={suite}
            pending={pending}
            action={action}
          />
        </>
      )}
      <article className="workspace-card">
        <h2>Historial y más resultados</h2>
        <p>
          Los resultados conservan su versión y revisión original. Editar
          después no los actualiza.
        </p>
        <nav aria-label="Páginas de publicación">
          {["candidates", "runs", "accounts", "versions"].map((section) => (
            <Link
              key={section}
              className="workspace-secondary"
              href={`?section=${section}`}
            >
              {
                {
                  candidates: "Versiones de prueba",
                  runs: "Pruebas",
                  accounts: "Números",
                  versions: "Publicadas",
                }[section as "candidates"]
              }
            </Link>
          ))}
          {state.next_cursor && (
            <Link
              href={`?section=${state.section}&cursor=${encodeURIComponent(state.next_cursor)}`}
            >
              Ver más
            </Link>
          )}
        </nav>
      </article>
    </section>
  );
}
