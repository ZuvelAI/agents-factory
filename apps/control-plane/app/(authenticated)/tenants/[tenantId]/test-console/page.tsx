import { Simulator } from "../../../../../components/test-console/simulator";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import type { TestReadiness } from "../../../../../lib/conversations";

export default async function TenantTestConsolePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  const readiness = await callAuthenticatedBackend<TestReadiness>(
    `/admin/tenants/${encodeURIComponent(tenantId)}/test-console/readiness`,
  );
  return (
    <section className="tenant-section test-console-page">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Onboarding · Test</p>
        <h2>Safe Test Console</h2>
        <p>
          Inspect the exact AgentSpec, Knowledge, policy and tool evidence
          without risking a Production write.
        </p>
      </header>
      <Simulator readiness={readiness} tenantId={tenantId} />
    </section>
  );
}
