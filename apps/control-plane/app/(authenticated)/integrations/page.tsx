import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function IntegrationsPage() {
  return (
    <TenantWorkspace
      title="Integrations"
      description="Sistemas externos requeridos, permisos y estado de sus conexiones."
      onboardingStep="integrations"
      actionLabel="Configurar integraciones"
    />
  );
}
