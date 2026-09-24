import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function SettingsPage() {
  return (
    <TenantWorkspace
      title="Settings"
      description="Configuración de plataforma y responsables operativos."
      emptyMessage="Las credenciales permanecen fuera del navegador y se resuelven únicamente en el backend."
      onboardingStep="policies-identity"
      actionLabel="Configurar políticas"
    />
  );
}
