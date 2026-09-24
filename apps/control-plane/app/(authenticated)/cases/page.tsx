import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function CasesPage() {
  return (
    <TenantWorkspace
      title="Cases"
      description="Casos que requieren seguimiento, revisión o resolución empresarial."
      emptyMessage="Todavía no hay casos registrados para el piloto."
      onboardingStep="human-operations"
      actionLabel="Configurar operación humana"
    />
  );
}
