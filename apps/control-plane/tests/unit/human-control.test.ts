import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { callAuthenticatedBackend } from "../../lib/api";
import WhatsAppSetupPage from "../../app/(authenticated)/tenants/[tenantId]/whatsapp/page";

vi.mock("../../lib/api", () => ({
  callAuthenticatedBackend: vi.fn(),
}));
vi.mock(
  "../../app/(authenticated)/tenants/[tenantId]/whatsapp/embedded-signup",
  () => ({
    EmbeddedSignup: () => null,
  }),
);
vi.mock(
  "../../app/(authenticated)/tenants/[tenantId]/whatsapp/test-message",
  () => ({
    TestMessage: () => null,
  }),
);
vi.mock(
  "../../app/(authenticated)/tenants/[tenantId]/whatsapp/coexistence-sync",
  () => ({
    CoexistenceSync: () => null,
  }),
);

const getBackend = vi.mocked(callAuthenticatedBackend);
const tenantId = "019c2000-0000-7000-8000-000000000101";
const accountId = "019c2000-0000-7000-8000-000000000202";
const conversationId = "019c2000-0000-7000-8000-000000000303";
const eligibleAccount = {
  id: accountId,
  business_id: null,
  waba_id: "waba-123",
  phone_number_id: "phone-123",
  status: "active",
  mode: "COEXISTENCE",
  coexistence_eligibility: "ELIGIBLE",
  granted_scopes: [],
  health_status: "HEALTHY",
  last_health_checked_at: null,
  token_expires_at: null,
  verified_at: null,
};

beforeEach(() => {
  getBackend.mockReset();
});

describe("human control in the WhatsApp account", () => {
  it("shows only a masked human conversation with an explicit resume confirmation", async () => {
    getBackend.mockImplementation(async (path) => {
      if (path.endsWith("/whatsapp")) {
        return [eligibleAccount];
      }
      if (path.endsWith("/human-active-conversations")) {
        return [
          {
            conversation_id: conversationId,
            customer_hint: "***0002",
            state_version: 3,
          },
        ];
      }
      throw new Error(`Unexpected endpoint: ${path}`);
    });

    const markup = renderToStaticMarkup(
      await WhatsAppSetupPage({ params: Promise.resolve({ tenantId }) }),
    );

    expect(markup).toContain("Conversaciones en atención humana");
    expect(markup).toContain("***0002");
    expect(markup).toContain("Confirmar reactivación");
    expect(markup).toContain(`name="expectedVersion" value="3"`);
    expect(markup).not.toContain("573000000002");
  });

  it("does not offer the control for API-only numbers", async () => {
    getBackend.mockImplementation(async (path) => {
      if (path.endsWith("/whatsapp")) {
        return [{ ...eligibleAccount, mode: "API_ONLY" }];
      }
      throw new Error(`Unexpected endpoint: ${path}`);
    });

    const markup = renderToStaticMarkup(
      await WhatsAppSetupPage({ params: Promise.resolve({ tenantId }) }),
    );

    expect(markup).not.toContain("Conversaciones en atención humana");
  });

  it("shows unavailable rather than empty when conversation data is malformed", async () => {
    getBackend.mockImplementation(async (path) => {
      if (path.endsWith("/whatsapp")) return [eligibleAccount];
      if (path.endsWith("/human-active-conversations")) {
        return [
          { conversation_id: conversationId, customer_wa_id: "573000000002" },
        ];
      }
      throw new Error(`Unexpected endpoint: ${path}`);
    });

    const markup = renderToStaticMarkup(
      await WhatsAppSetupPage({ params: Promise.resolve({ tenantId }) }),
    );

    expect(markup).toContain(
      "No se pudo consultar el control de conversaciones.",
    );
    expect(markup).not.toContain("No hay conversaciones bajo control humano");
    expect(markup).not.toContain("573000000002");
  });

  it("rejects a conversation identifier that is not a UUID", async () => {
    getBackend.mockImplementation(async (path) => {
      if (path.endsWith("/whatsapp")) return [eligibleAccount];
      if (path.endsWith("/human-active-conversations")) {
        return [
          {
            conversation_id: "000000000000000000000000000000000000",
            customer_hint: "***0002",
            state_version: 3,
          },
        ];
      }
      throw new Error(`Unexpected endpoint: ${path}`);
    });

    const markup = renderToStaticMarkup(
      await WhatsAppSetupPage({ params: Promise.resolve({ tenantId }) }),
    );

    expect(markup).toContain(
      "No se pudo consultar el control de conversaciones.",
    );
    expect(markup).not.toContain("Confirmar reactivación");
  });
});
