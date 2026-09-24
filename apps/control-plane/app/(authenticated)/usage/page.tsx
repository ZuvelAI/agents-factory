import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function UsagePage() {
  return (
    <TenantWorkspace
      title="Usage & Costs"
      description="Uso y costos atribuibles por tenant, proveedor y operación."
      emptyMessage="Aún no hay consumo del agente piloto para mostrar."
    />
  );
}
