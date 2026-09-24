import { describe, expect, it } from "vitest";
import { parseSignupEvent } from "../../lib/whatsapp-signup-event";

const origin = "https://www.facebook.com";
const coexistence = {
  type: "WA_EMBEDDED_SIGNUP",
  event: "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
  version: 3,
  data: { waba_id: "123" },
};
const exclusive = {
  type: "WA_EMBEDDED_SIGNUP",
  event: "FINISH",
  data: { waba_id: "123", business_id: "456", phone_number_id: "789" },
};

describe("mode-bound Meta signup events", () => {
  it("accepts coexistence with only the WABA returned by Meta", () => {
    expect(
      parseSignupEvent(origin, JSON.stringify(coexistence), "COEXISTENCE"),
    ).toEqual({ wabaId: "123", businessId: null, phoneNumberId: null });
  });
  it("preserves exclusive API asset identifiers", () => {
    expect(parseSignupEvent(origin, exclusive, "API_ONLY")).toEqual({
      wabaId: "123",
      businessId: "456",
      phoneNumberId: "789",
    });
  });
  it("rejects mode substitution in either direction", () => {
    expect(parseSignupEvent(origin, exclusive, "COEXISTENCE")).toBeNull();
    expect(parseSignupEvent(origin, coexistence, "API_ONLY")).toBeNull();
  });
  it("rejects untrusted origins and malformed payloads", () => {
    expect(
      parseSignupEvent(
        "https://www.facebook.com.attacker.test",
        coexistence,
        "COEXISTENCE",
      ),
    ).toBeNull();
    for (const payload of [
      null,
      "{",
      {},
      { ...coexistence, data: { waba_id: "" } },
    ]) {
      expect(parseSignupEvent(origin, payload, "COEXISTENCE")).toBeNull();
    }
  });
  it("does not accept incomplete exclusive registrations", () => {
    expect(
      parseSignupEvent(
        origin,
        { ...exclusive, data: { waba_id: "123" } },
        "API_ONLY",
      ),
    ).toBeNull();
  });
});
