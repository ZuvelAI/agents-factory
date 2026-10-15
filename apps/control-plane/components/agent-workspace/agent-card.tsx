import Link from "next/link";
import type { AgentSummary } from "../../lib/agent-workspace";
import { UiIcon } from "../ui-icon";
import { StatusSummary } from "./status-summary";

export function AgentCard({ agent }: { agent: AgentSummary }) {
  return (
    <article className="workspace-card">
      <header className="workspace-card-heading">
        <span className="workspace-avatar workspace-avatar-agent">
          <UiIcon name="agents" size={24} />
        </span>
        <h2>{agent.display_name}</h2>
      </header>
      <StatusSummary agent={agent} />
      <p className="workspace-muted">
        {agent.purpose ??
          "Abre el agente para consultar su configuración y versiones."}
      </p>
      <div className="workspace-channel-list">
        {agent.channel_accounts.length ? (
          agent.channel_accounts.map((c) => (
            <p key={c.account_id}>
              <UiIcon name="whatsapp" size={16} />{" "}
              {c.display_number ?? "WhatsApp"} ·{" "}
              {
                {
                  connected: "Conectado",
                  disconnected: "Desconectado",
                  review_required: "Revisar conexión",
                  unknown: "Sin verificar",
                }[c.connection_status]
              }
            </p>
          ))
        ) : (
          <p className="workspace-muted">Sin número asignado</p>
        )}
      </div>
      <div className="workspace-card-actions">
        <Link
          className="workspace-open"
          href={`/tenants/${agent.tenant_id}/agents/${agent.id}`}
        >
          Abrir agente <span aria-hidden>→</span>
        </Link>
        <Link
          className="workspace-secondary"
          href={`/conversations?tenant=${agent.tenant_id}&agent=${agent.id}`}
        >
          Conversaciones
        </Link>
      </div>
    </article>
  );
}
