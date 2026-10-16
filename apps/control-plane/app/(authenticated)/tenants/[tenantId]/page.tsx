import Link from "next/link";
import { isWorkspaceId, readAgents } from "../../../../lib/agent-workspace";
import { AgentCard } from "../../../../components/agent-workspace/agent-card";

export default async function CompanyPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams?: Promise<{ cursor?: string }>;
}) {
  const { tenantId } = await params;
  let data;
  try {
    if (!isWorkspaceId(tenantId)) throw new Error("Invalid company");
    data = await readAgents(tenantId, (await searchParams)?.cursor);
  } catch {
    return (
      <section className="workspace">
        <h1>Empresa no disponible</h1>
        <p>No pudimos consultar sus agentes.</p>
        <Link href="/tenants">Volver a empresas</Link>
      </section>
    );
  }
  return (
    <section className="workspace">
      <Link className="workspace-back" href="/tenants">
        ← Empresas
      </Link>
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Espacio de empresa</p>
          <h1>{data.company_name ?? "Agentes de la empresa"}</h1>
          <p className="workspace-muted">
            Configuración y conversaciones, agente por agente.
          </p>
        </div>
        <div>
          <Link
            className="workspace-secondary"
            href={`/tenants/${tenantId}/agents/new`}
          >
            + Nuevo agente
          </Link>
          <Link
            className="workspace-secondary"
            href={`/tenants/${tenantId}/settings`}
          >
            Información empresarial
          </Link>
        </div>
      </header>
      <div className="workspace-grid">
        {data.items.map((agent) => (
          <AgentCard agent={agent} key={agent.id} />
        ))}
      </div>
      {!data.items.length ? (
        <div className="workspace-empty">
          <h2>Esta empresa todavía no tiene agentes</h2>
          <p>No hemos creado ni conectado ninguno automáticamente.</p>
        </div>
      ) : null}
      {data.next_cursor ? (
        <Link
          className="workspace-secondary"
          href={`/tenants/${tenantId}?cursor=${encodeURIComponent(data.next_cursor)}`}
        >
          Más agentes →
        </Link>
      ) : null}
      <div className="workspace-footer-links">
        <Link href={`/conversation-log?tenant=${tenantId}`}>
          Ver conversaciones de la empresa
        </Link>
        <details>
          <summary>Administración avanzada</summary>
          <Link href={`/tenants/${tenantId}/onboarding/company`}>
            Configuración anterior
          </Link>
          <br />
          <Link href={`/tenants/${tenantId}/whatsapp`}>
            Conexión WhatsApp existente
          </Link>
        </details>
      </div>
    </section>
  );
}
