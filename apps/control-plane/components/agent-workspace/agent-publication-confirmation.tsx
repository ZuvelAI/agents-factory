"use client";
import { useState } from "react";
import type {
  Candidate,
  PublicationState,
  Run,
} from "../../lib/workspace-publication";

export function AgentPublicationConfirmation({
  tenant,
  agent,
  state,
  candidate,
  run,
  pending,
  action,
}: {
  tenant: string;
  agent: string;
  state: PublicationState;
  candidate: Candidate;
  run: Run | undefined;
  pending: boolean;
  action: (form: FormData) => void;
}) {
  const [accountId, setAccountId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [rollbackId, setRollbackId] = useState("");
  const [rollbackConfirmed, setRollbackConfirmed] = useState(false);
  const account = state.accounts.find((a) => a.id === accountId);
  const ready =
    run?.run_kind === "SCENARIOS" &&
    run.is_current &&
    run.approved === true &&
    run.version_id === candidate.version.id &&
    run.result &&
    "checks_passed" in run.result &&
    run.result.checks_passed;
  const scope = (
    <>
      <input type="hidden" name="tenantId" value={tenant} />
      <input type="hidden" name="agentId" value={agent} />
      <input type="hidden" name="revision" value={state.draft_revision} />
      <input type="hidden" name="accountId" value={accountId} />
      <input
        type="hidden"
        name="bindingRevision"
        value={account?.binding?.revision ?? 0}
      />
    </>
  );
  return (
    <article className="workspace-card">
      <h2>Publicación y recuperación</h2>
      <p>
        Empresa: {candidate.version.business_name} · Agente: {agent} · Destino:
        versión {candidate.version.version_number}
      </p>
      <label>
        Número destino
        <select
          value={accountId}
          onChange={(event) => {
            setAccountId(event.target.value);
            setConfirmed(false);
            setRollbackId("");
            setRollbackConfirmed(false);
          }}
          disabled={pending}
        >
          <option value="">Selecciona un número</option>
          {state.accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.display_phone_number ?? a.id} · {a.health_status}
            </option>
          ))}
        </select>
      </label>
      {account && (
        <p>
          Asignación actual:{" "}
          {account.binding
            ? `${account.binding.agent_instance_id} · versión ${account.binding.version_id} · revisión ${account.binding.revision}`
            : "Sin agente asignado"}
          . La publicación reemplazará esta asignación.
        </p>
      )}
      <details>
        <summary>Comparar versión destino y publicada</summary>
        <h3>Destino</h3>
        <pre className="workspace-version">
          {candidate.version.instructions}
        </pre>
        {[account?.current_version]
          .filter((v) => v !== undefined && v !== null)
          .map((v) => (
            <div key={v.id}>
              <h3>Actual · versión {v.version_number}</h3>
              <pre className="workspace-version">{v.instructions}</pre>
            </div>
          ))}
      </details>
      <form action={action}>
        {scope}
        <input type="hidden" name="command" value="publish" />
        <input type="hidden" name="versionId" value={candidate.version.id} />
        <input type="hidden" name="runId" value={run?.id ?? ""} />
        <input
          type="hidden"
          name="currentAgent"
          value={account?.binding?.agent_instance_id ?? ""}
        />
        <label>
          <input
            type="checkbox"
            name="confirmPublish"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            disabled={pending}
          />{" "}
          Confirmo la versión y el número destino
        </label>
        <button
          disabled={
            pending ||
            !ready ||
            !confirmed ||
            !account ||
            account.status !== "active" ||
            account.health_status !== "HEALTHY"
          }
        >
          Publicar en este número
        </button>
        {!ready && (
          <p className="workspace-muted">
            Antes de publicar debes aprobar escenarios vigentes de esta versión.
          </p>
        )}
      </form>
      {account?.binding?.agent_instance_id === agent && (
        <details>
          <summary>Volver a una versión anterior</summary>
          <form action={action}>
            {scope}
            <input type="hidden" name="command" value="rollback" />
            <label>
              Versión anterior
              <select
                name="versionId"
                value={rollbackId}
                onChange={(event) => {
                  setRollbackId(event.target.value);
                  setRollbackConfirmed(false);
                }}
                disabled={pending}
              >
                <option value="">Selecciona una versión publicada</option>
                {state.versions
                  .filter(
                    (v) =>
                      state.rollback_targets.includes(v.id) &&
                      v.id !== account.binding?.version_id,
                  )
                  .map((v) => (
                    <option key={v.id} value={v.id}>
                      Versión {v.version_number} · {v.model}
                    </option>
                  ))}
              </select>
            </label>
            {state.versions
              .filter((v) => v.id === rollbackId)
              .map((v) => (
                <pre className="workspace-version" key={v.id}>
                  {v.instructions}
                </pre>
              ))}
            <label>
              <input
                type="checkbox"
                name="confirmRollback"
                checked={rollbackConfirmed}
                onChange={(event) => setRollbackConfirmed(event.target.checked)}
                disabled={pending}
              />{" "}
              Confirmo recuperar esta versión en el número seleccionado
            </label>
            <button disabled={pending || !rollbackId || !rollbackConfirmed}>
              Recuperar versión
            </button>
            <p className="workspace-muted">
              Se conserva el borrador actual; no se borra historial ni se
              desconecta Meta.
            </p>
          </form>
        </details>
      )}
    </article>
  );
}
