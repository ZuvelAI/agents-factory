import { CreateEntityForm } from "../../../../../../components/agent-workspace/company-profile-form";
import { isWorkspaceId } from "../../../../../../lib/agent-workspace";
export default async function NewAgentPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  if (!isWorkspaceId(tenantId)) return <p>Empresa no disponible.</p>;
  return <CreateEntityForm tenant={tenantId} />;
}
