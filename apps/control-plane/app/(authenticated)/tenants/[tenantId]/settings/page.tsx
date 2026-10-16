import Link from "next/link";
import { CompanyProfileForm } from "../../../../../components/agent-workspace/company-profile-form";
import { readProfile } from "../../../../../lib/agent-configuration";
import { readAgents } from "../../../../../lib/agent-workspace";
import { BackendProblem } from "../../../../../lib/api";
export default async function CompanySettings({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  let profile = null,
    name = "";
  try {
    const agents = await readAgents(tenantId);
    name = agents.company_name ?? "";
    try {
      profile = await readProfile(tenantId);
    } catch (error) {
      if (
        !(
          error instanceof BackendProblem &&
          error.code === "company_profile_missing"
        )
      )
        throw error;
    }
  } catch {
    return (
      <section className="workspace">
        <h1>Información no disponible</h1>
        <p>No se ha cambiado la empresa.</p>
        <Link href="/tenants">Volver a empresas</Link>
      </section>
    );
  }
  return <CompanyProfileForm tenant={tenantId} name={name} initial={profile} />;
}
