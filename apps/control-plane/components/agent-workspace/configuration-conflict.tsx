"use client";

import { useState, useTransition } from "react";
import type { Draft } from "../../lib/agent-configuration";
import { compareAgentConfiguration } from "./configuration-actions";

export function ConfigurationConflict({
  local,
  onAccept,
}: {
  local: Draft;
  onAccept: (current: Draft) => void;
}) {
  const [current, setCurrent] = useState<Draft | null>(null),
    [pending, start] = useTransition();
  const [failed, setFailed] = useState(false);
  return (
    <aside className="workspace-card" role="alert">
      <h2>Hay otra revisión guardada</h2>
      <p>
        Tu texto sigue en el formulario. Consultar la revisión actual no lo
        reemplaza.
      </p>
      <button
        type="button"
        disabled={pending}
        onClick={() =>
          start(async () => {
            const result = await compareAgentConfiguration(
              local.tenant_id,
              local.agent_instance_id,
            );
            setCurrent(result.draft ?? null);
            setFailed(!result.draft);
          })
        }
      >
        Recargar para comparar
      </button>
      {failed ? (
        <p>No pudimos cargar la comparación. Tu texto se conserva.</p>
      ) : null}
      {current ? (
        <>
          <div className="workspace-detail-grid">
            <details>
              <summary>Tu borrador sin guardar</summary>
              <pre>{JSON.stringify(local.configuration, null, 2)}</pre>
            </details>
            <details open>
              <summary>Guardado: revisión {current.revision}</summary>
              <pre>{JSON.stringify(current.configuration, null, 2)}</pre>
            </details>
          </div>
          <button type="button" onClick={() => onAccept(current)}>
            Usar revisión guardada y descartar mi texto
          </button>
          <p>
            Para combinar ambos, conserva primero tu texto y aplícalo después de
            cargar la revisión guardada. No se sobrescribe automáticamente.
          </p>
        </>
      ) : null}
    </aside>
  );
}
