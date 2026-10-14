import Link from "next/link";
import { callAuthenticatedBackend } from "../../lib/api";
import {
  prepareAgentCandidate,
  testAgentCandidate,
  reviewAgentTests,
  rollbackAgent,
} from "./agent-publication-actions";
import { PublishAccountForm } from "./publish-account-form";

type Version = { id: string; version_number: number; state: string };
type Account = {
  id: string;
  display_phone_number: string | null;
  status: string;
  health_status: string;
};
type Binding = {
  whatsapp_account_id: string;
  version_id: string;
  revision: number;
};
type State = {
  saved_revision: number;
  candidates: Version[];
  accounts: Account[];
  bindings: Binding[];
  blockers: string[];
};
type Run = {
  id: string;
  version_id: string;
  onboarding_revision: number;
  is_current: boolean;
  approved: boolean | null;
  expires_at: string;
  result: null | {
    checks_passed: boolean;
    scenarios: {
      key: string;
      prompt: string;
      response: string | null;
      passed: boolean;
      error_code: string | null;
    }[];
  };
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function AgentPublication({
  tenantId,
  step,
  runId,
  candidateId,
  error,
}: {
  tenantId: string;
  step: string;
  runId?: string;
  candidateId?: string;
  error?: string;
}) {
  let state: State,
    run: Run | null = null;
  try {
    if (!uuid.test(tenantId)) throw new Error("invalid tenant");
    state = await callAuthenticatedBackend<State>(
      `/admin/tenants/${tenantId}/agent-publication`,
    );
    if (
      !Number.isInteger(state.saved_revision) ||
      !Array.isArray(state.candidates) ||
      !Array.isArray(state.accounts) ||
      !Array.isArray(state.bindings) ||
      !Array.isArray(state.blockers)
    )
      throw new Error("invalid state");
    if (runId) {
      if (!uuid.test(runId)) throw new Error("invalid run");
      run = await callAuthenticatedBackend<Run>(
        `/admin/tenants/${tenantId}/agent-publication/tests/${runId}`,
      );
    }
  } catch {
    return (
      <p role="alert">
        No se pudo consultar el estado de publicación. Actualiza la página; tu
        configuración guardada se conserva.
      </p>
    );
  }
  const hidden = (
    <>
      <input type="hidden" name="tenantId" value={tenantId} />
      <input
        type="hidden"
        name="expectedRevision"
        value={state.saved_revision}
      />
    </>
  );
  const selected =
    candidateId && state.candidates.some((v) => v.id === candidateId)
      ? candidateId
      : "";
  const currentRun =
    run?.onboarding_revision === state.saved_revision &&
    run.is_current === true;
  const canPublish =
    run?.approved === true && run.result?.checks_passed === true && currentRun;
  return (
    <section
      className="requirements-card"
      aria-label="Configuración y publicación del agente"
    >
      <h2>Versión del agente</h2>
      <p>
        Revisión guardada: {state.saved_revision}. Guardar no cambia la versión
        activa.
      </p>
      <p>
        Knowledge usa el resumen que aprobaste. Una referencia a PDF o web no
        importa su contenido automáticamente.
      </p>
      {error ? (
        <p role="alert">
          {error.includes("stale")
            ? "La configuración cambió. Actualiza y prepara una nueva versión."
            : "No se pudo completar la acción. Revisa los requisitos y vuelve a intentarlo."}
        </p>
      ) : null}
      {state.bindings.length === 0 ? (
        <p>
          Ningún agente publicado para estas cuentas; las no asignadas siguen
          usando el agente genérico.
        </p>
      ) : (
        <ul>
          {state.bindings.map((binding) => (
            <li key={binding.whatsapp_account_id}>
              Cuenta{" "}
              {state.accounts.find((a) => a.id === binding.whatsapp_account_id)
                ?.display_phone_number ?? binding.whatsapp_account_id}
              : versión activa {binding.version_id}, asignación{" "}
              {binding.revision}.
            </li>
          ))}
        </ul>
      )}
      {step === "whatsapp" ? (
        <p>
          {state.accounts.some(
            (a) => a.status === "active" && a.health_status === "HEALTHY",
          )
            ? "WhatsApp ya está conectado. No necesitas reconectar el número."
            : "No hay una cuenta activa y saludable disponible."}
        </p>
      ) : null}
      {state.blockers.length > 0 ? (
        <ul>
          {state.blockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      ) : null}
      <form action={prepareAgentCandidate}>
        {hidden}
        <button
          type="submit"
          disabled={state.blockers.length > 0 || state.saved_revision < 1}
        >
          Preparar candidato
        </button>
      </form>
      <form action={testAgentCandidate}>
        {hidden}
        <label>
          Versión que quieres probar
          <select name="versionId" defaultValue={selected} required>
            <option value="">Elige un candidato</option>
            {state.candidates.map((v) => (
              <option key={v.id} value={v.id}>
                Versión {v.version_number} · {v.state}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={state.candidates.length === 0}>
          Probar respuestas
        </button>
        <p>
          Las pruebas usan OpenAI y pueden generar consumo de API. No envían
          mensajes a clientes.
        </p>
      </form>
      {run ? (
        <section aria-label="Respuestas de prueba">
          <h3>Pruebas del candidato</h3>
          {!currentRun && run.result ? (
            <p role="alert">
              Las pruebas vencieron o pertenecen a otra revisión. Prepara y
              prueba el candidato actual.
            </p>
          ) : null}
          {!run.result ? (
            <p>
              Pruebas pendientes. Usa Actualizar para consultar el resultado.
            </p>
          ) : (
            <>
              <p>
                {run.result.checks_passed
                  ? "Comprobaciones técnicas superadas. Revisa la marca, los hechos y los límites de cada respuesta."
                  : "Las comprobaciones no pasaron. No se puede publicar esta prueba."}
              </p>
              {run.result.scenarios.map((s) => (
                <article key={s.key}>
                  <h4>{s.key}</h4>
                  <p>{s.prompt}</p>
                  {s.response ? (
                    <p style={{ whiteSpace: "pre-wrap" }}>{s.response}</p>
                  ) : (
                    <p>
                      {s.key === "human_control" && s.passed
                        ? "Comprobación determinista: la IA permanece en silencio durante atención humana."
                        : `Sin respuesta válida (${s.error_code ?? "pendiente"}).`}
                    </p>
                  )}
                </article>
              ))}
              <p>
                Revisión:{" "}
                {run.approved === null
                  ? "pendiente"
                  : run.approved
                    ? "aprobada"
                    : "rechazada"}
                . La aprobación no es una certificación automática.
              </p>
              {run.approved === null ? (
                <form action={reviewAgentTests}>
                  {hidden}
                  <input type="hidden" name="runId" value={run.id} />
                  <label>
                    <input type="checkbox" name="confirmReview" required />
                    Revisé todas las respuestas: representan la marca, no
                    inventan hechos y respetan los límites.
                  </label>
                  <button
                    type="submit"
                    name="decision"
                    value="approve"
                    disabled={!run.result.checks_passed || !currentRun}
                  >
                    Aprobar revisión
                  </button>
                  <button
                    type="submit"
                    name="decision"
                    value="reject"
                    formNoValidate
                  >
                    Rechazar revisión
                  </button>
                </form>
              ) : null}
            </>
          )}
          <Link href={`/tenants/${tenantId}/onboarding/${step}?run=${run.id}`}>
            Actualizar resultados
          </Link>
        </section>
      ) : null}
      <h3>Asignación a WhatsApp</h3>
      {canPublish && run ? (
        <PublishAccountForm
          tenantId={tenantId}
          revision={state.saved_revision}
          runId={run.id}
          versionId={run.version_id}
          accounts={state.accounts}
          bindings={state.bindings}
        />
      ) : (
        <p>
          Primero prueba y aprueba el candidato. Después podrás publicar en una
          cuenta seleccionada explícitamente.
        </p>
      )}
      <p>
        Las pruebas vencen para nuevas publicaciones; una versión ya activa no
        se desactiva por ese vencimiento.
      </p>
      {state.bindings.map((binding) => (
        <form key={binding.whatsapp_account_id} action={rollbackAgent}>
          {hidden}
          <input
            type="hidden"
            name="accountId"
            value={binding.whatsapp_account_id}
          />
          <input
            type="hidden"
            name="expectedBindingRevision"
            value={binding.revision}
          />
          <label>
            Volver a una versión publicada para cuenta{" "}
            {state.accounts.find((a) => a.id === binding.whatsapp_account_id)
              ?.display_phone_number ?? binding.whatsapp_account_id}
            <select name="versionId" defaultValue="" required>
              <option value="">Elige versión anterior compatible</option>
              {state.candidates
                .filter(
                  (v) =>
                    v.state === "PRODUCTION" && v.id !== binding.version_id,
                )
                .map((v) => (
                  <option key={v.id} value={v.id}>
                    Versión {v.version_number}
                  </option>
                ))}
            </select>
          </label>
          <label>
            <input type="checkbox" name="confirmRollback" required />
            Confirmo volver a la versión seleccionada.
          </label>
          <button type="submit">Volver a versión anterior</button>
        </form>
      ))}
    </section>
  );
}
