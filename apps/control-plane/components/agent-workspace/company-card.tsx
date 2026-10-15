import Link from "next/link";
import type { CompanySummary } from "../../lib/agent-workspace";
import { UiIcon } from "../ui-icon";

export function CompanyCard({ company }: { company: CompanySummary }) {
  return (
    <article className="workspace-card company-card">
      <header className="workspace-card-heading">
        <span className="workspace-avatar">
          <UiIcon name="tenants" size={24} />
        </span>
        <div>
          <h2>{company.name}</h2>
          <span className="workspace-muted">
            {company.agent_count
              ? `${company.agent_count} ${company.agent_count === 1 ? "agente" : "agentes"}`
              : "Sin agentes"}
          </span>
        </div>
      </header>
      <ul className="workspace-preview">
        {company.agents.map((agent) => (
          <li key={agent.id}>
            <UiIcon name="agents" size={16} />
            <span>{agent.display_name}</span>
            <span className="workspace-mini-state">
              {agent.execution_status === "serving"
                ? "Atendiendo"
                : agent.execution_status === "unassigned"
                  ? "Sin canal"
                  : "Ver estado"}
            </span>
          </li>
        ))}
      </ul>
      {company.agent_count > company.agents.length ? (
        <p className="workspace-muted">Más agentes dentro de la empresa</p>
      ) : null}
      <Link className="workspace-open" href={`/tenants/${company.id}`}>
        Ver empresa <span aria-hidden>→</span>
      </Link>
    </article>
  );
}
