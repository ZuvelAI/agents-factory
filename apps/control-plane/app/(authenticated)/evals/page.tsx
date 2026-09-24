import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function EvalsPage() {
  return (
    <TenantWorkspace
      title="Evals"
      description="Evaluaciones vinculadas a la versión exacta del agente."
      emptyMessage="No hay ejecuciones todavía. El wizard mantendrá Test y Quality Gate bloqueados hasta que exista evidencia real."
      onboardingStep="test"
      actionLabel="Ver estado de Test"
    />
  );
}
