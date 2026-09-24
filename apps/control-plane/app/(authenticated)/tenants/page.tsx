import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function TenantsPage() {
  return (
    <TenantWorkspace
      title="Tenants"
      description="Clientes aislados administrados por Agents Factory."
      onboardingStep="company"
      actionLabel="Abrir onboarding"
    />
  );
}
