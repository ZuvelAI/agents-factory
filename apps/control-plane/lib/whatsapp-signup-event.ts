import type { WhatsAppMode } from "./whatsapp-mode";

export type EmbeddedSignupAssets = {
  businessId: string | null;
  wabaId: string;
  phoneNumberId: string | null;
};

export function parseSignupEvent(
  origin: string,
  value: unknown,
  mode: WhatsAppMode,
): EmbeddedSignupAssets | null {
  if (
    origin !== "https://www.facebook.com" &&
    origin !== "https://web.facebook.com"
  )
    return null;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== "object") return null;
  const payload = value as Record<string, unknown>;
  const expected =
    mode === "COEXISTENCE"
      ? "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"
      : "FINISH";
  if (
    payload.type !== "WA_EMBEDDED_SIGNUP" ||
    payload.event !== expected ||
    !payload.data ||
    typeof payload.data !== "object"
  )
    return null;
  const data = payload.data as Record<string, unknown>;
  const identifier = (item: unknown): string | null =>
    typeof item === "string" && item.trim().length > 0 ? item : null;
  const wabaId = identifier(data.waba_id);
  const businessId = identifier(data.business_id);
  const phoneNumberId = identifier(data.phone_number_id);
  if (!wabaId || (mode === "API_ONLY" && (!businessId || !phoneNumberId)))
    return null;
  return { wabaId, businessId, phoneNumberId };
}
