import Link from "next/link";
import { readAgent } from "../../../../../../lib/agent-workspace";
import { AgentOverviewPanel } from "../../../../../../components/agent-workspace/agent-overview";
import { readAgentOperation } from "../../../../../../lib/agent-operations";

export default async function AgentPage({
  params,
}: {
  params: Promise<{ tenantId: string; agentId: string }>;
}) {
  const { tenantId, agentId } = await params;
  let overview;
  let operation = null;
  try {
    [overview, operation] = await Promise.all([
      readAgent(tenantId, agentId),
      readAgentOperation(tenantId, agentId).catch(() => null),
    ]);
  } catch {
    return (
      <section className="workspace">
        <h1>Agente no disponible</h1>
        <p>
          No pudimos consultar su configuración. No se ha modificado el agente.
        </p>
        <Link href="/tenants">Volver a empresas</Link>
      </section>
    );
  }
  return (
    <AgentOverviewPanel
      key={`${tenantId}:${agentId}`}
      overview={overview}
      operation={operation}
    />
  );
}
