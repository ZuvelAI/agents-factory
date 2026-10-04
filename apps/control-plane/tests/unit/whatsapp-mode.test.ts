import { describe, expect, it } from "vitest";
import {
  signupBlockReason,
  isCoexistenceSignupEnabled,
} from "../../lib/whatsapp-mode";

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
  it("opens only a server-enabled coexistence pilot, still requiring an explicit choice", () => {
    expect(signupBlockReason("COEXISTENCE", false, true)).toBeNull();
    expect(signupBlockReason(null, false, true)).not.toBeNull();
    expect(signupBlockReason("API_ONLY", false, true)).not.toBeNull();
  });
  it.each([
    null,
    undefined,
    true,
    {},
    { coexistence_enabled: "true" },
    { coexistence_enabled: false },
  ])(
    "does not enable signup from malformed or absent availability (%j)",
    (value) => {
      expect(isCoexistenceSignupEnabled(value)).toBe(false);
    },
  );
  it("accepts the backend's explicit enabled permission", () => {
    expect(isCoexistenceSignupEnabled({ coexistence_enabled: true })).toBe(
      true,
    );
  });
});
