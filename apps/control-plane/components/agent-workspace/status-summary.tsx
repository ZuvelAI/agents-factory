import type { AgentSummary } from "../../lib/agent-workspace";

export function StatusSummary({ agent }: { agent: AgentSummary }) {
  const status = {
    unknown: "Ejecución sin verificar",
    unassigned: "Sin canal",
    error: "Requiere atención",
    paused: "Pausado",
    serving: "Atendiendo",
  }[agent.execution_status];
  return (
    <div className="workspace-badges">
      <span
        className={`workspace-status workspace-status-${agent.execution_status}`}
      >
        {status}
      </span>
      <span className="workspace-tag">
        {agent.published_version_id ? "Publicado" : "Sin publicar"}
      </span>
      {agent.has_pending_changes ? (
        <span className="workspace-tag workspace-pending">
          Cambios pendientes
        </span>
      ) : null}
    </div>
  );
}
