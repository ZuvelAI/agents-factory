import { describe, expect, it } from "vitest";
import { signupBlockReason } from "../../lib/whatsapp-mode";

describe("WhatsApp onboarding mode safety", () => {
  it("requires an explicit choice", () => {
    expect(signupBlockReason(null, true)).not.toBeNull();
  });
  it("requires consent for an exclusive number", () => {
    expect(signupBlockReason("API_ONLY", false)).not.toBeNull();
    expect(signupBlockReason("API_ONLY", true)).toBeNull();
  });
  it("never silently falls back from coexistence to API-only", () => {
    expect(signupBlockReason("COEXISTENCE", true)).toContain("pendiente");
    expect(signupBlockReason("COEXISTENCE", false)).toContain("pendiente");
  });
});
