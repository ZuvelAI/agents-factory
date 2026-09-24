import { TenantWorkspace } from "../../../components/tenant-workspace";

export default function ConversationsPage() {
  return (
    <TenantWorkspace
      title="Conversations"
      description="Conversaciones y mensajes observables por tenant."
      emptyMessage="Todavía no hay conversaciones. Aparecerán cuando se conecte WhatsApp y comiencen las pruebas del agente."
      onboardingStep="whatsapp"
      actionLabel="Preparar WhatsApp"
    />
  );
}
