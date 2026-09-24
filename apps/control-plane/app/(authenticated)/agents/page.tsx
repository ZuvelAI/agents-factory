import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function AgentsPage() {
  return (
    <TenantWorkspace
      title="Agents"
      description="Configuración guiada de identidad, voz, idiomas y alcance de cada agente."
      onboardingStep="agent"
      actionLabel="Configurar agente"
    />
  );
}
