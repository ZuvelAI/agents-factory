import Link from "next/link";
import { readAgent } from "../../../../../../lib/agent-workspace";
import { AgentOverviewPanel } from "../../../../../../components/agent-workspace/agent-overview";

export default async function AgentPage({
  params,
}: {
  params: Promise<{ tenantId: string; agentId: string }>;
}) {
  const { tenantId, agentId } = await params;
  let overview;
  try {
    overview = await readAgent(tenantId, agentId);
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
  return <AgentOverviewPanel overview={overview} />;
}
