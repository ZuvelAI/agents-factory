export type WhatsAppMode = "API_ONLY" | "COEXISTENCE";

// Do not expose the live coexistence flow before webhook synchronization and
// human takeover have been verified end to end. This is not Meta eligibility.
export function signupBlockReason(
  mode: WhatsAppMode | null,
  confirmedExclusive: boolean,
): string | null {
  if (!mode) return "Selecciona cómo quieres usar WhatsApp.";
  if (mode === "COEXISTENCE") {
    return "Coexistencia pendiente de habilitación: conservaremos tu WhatsApp Business en el celular. No registres este número como exclusivo para el agente.";
  }
  if (!confirmedExclusive) {
    return "Confirma que usarás un número exclusivo, sin conservar su uso en la aplicación del celular.";
  }
  return null;
}
