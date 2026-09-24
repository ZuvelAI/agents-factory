import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function CapabilitiesPage() {
  return (
    <TenantWorkspace
      title="Capabilities"
      description="Casos de uso y Capability Packs autorizados para cada cliente."
      onboardingStep="capabilities"
      actionLabel="Configurar capabilities"
    />
  );
}
