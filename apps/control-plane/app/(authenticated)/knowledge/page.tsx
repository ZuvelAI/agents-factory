import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function KnowledgePage() {
  return (
    <TenantWorkspace
      title="Knowledge"
      description="Fuentes aprobadas, autoridad, revisión y resolución de conflictos."
      onboardingStep="knowledge"
      actionLabel="Configurar conocimiento"
    />
  );
}
