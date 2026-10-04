export type WhatsAppMode = "API_ONLY" | "COEXISTENCE";

// This permission controls rollout, not Meta eligibility. Unknown means closed.
export function isCoexistenceSignupEnabled(value: unknown): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    "coexistence_enabled" in value &&
    value.coexistence_enabled === true
  );
}

export function signupBlockReason(
  mode: WhatsAppMode | null,
  confirmedExclusive: boolean,
  coexistenceEnabled = false,
): string | null {
  if (!mode) return "Selecciona cómo quieres usar WhatsApp.";
  if (mode === "COEXISTENCE") {
    if (coexistenceEnabled) return null;
    return "Coexistencia pendiente de habilitación: conservaremos tu WhatsApp Business en el celular. No registres este número como exclusivo para el agente.";
  }
  if (!confirmedExclusive) {
    return "Confirma que usarás un número exclusivo, sin conservar su uso en la aplicación del celular.";
  }
  return null;
}
