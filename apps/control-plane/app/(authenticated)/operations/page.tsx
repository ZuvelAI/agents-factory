import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function OperationsPage() {
  return (
    <TenantWorkspace
      title="Operations"
      description="Salud de servicios, entregas, colas e incidentes operativos."
      emptyMessage="Los servicios locales están en ejecución. Los eventos aparecerán cuando comience el tráfico del piloto."
    />
  );
}
