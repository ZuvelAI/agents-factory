import Link from "next/link";
import { readPublication } from "../../../../../../../lib/workspace-publication";
import { AgentTestingPanel } from "../../../../../../../components/agent-workspace/agent-testing-panel";
export default async function TestAgentPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string; agentId: string }>;
  searchParams: Promise<{ cursor?: string; section?: string }>;
}) {
  const [{ tenantId, agentId }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  let state;
  try {
    state = await readPublication(
      tenantId,
      agentId,
      query.cursor,
      query.section ?? "candidates",
    );
  } catch {
    return (
      <section className="workspace">
        <h1>Pruebas no disponibles</h1>
        <p>
          No se pudo consultar la publicación. No se cambió el agente ni se
          inició una prueba.
        </p>
        <Link href={`/tenants/${tenantId}/agents/${agentId}/edit`}>
          Volver al borrador
        </Link>
      </section>
    );
  }
  return (
    <AgentTestingPanel
      key={`${tenantId}:${agentId}:${query.section ?? "candidates"}:${query.cursor ?? ""}`}
      tenant={tenantId}
      agent={agentId}
      initial={state}
    />
  );
}
