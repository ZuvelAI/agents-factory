import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";
import { AgentPublication } from "../../components/onboarding/agent-publication";
import { callAuthenticatedBackend } from "../../lib/api";

vi.mock("../../lib/api", () => ({ callAuthenticatedBackend: vi.fn() }));
vi.mock("../../components/onboarding/agent-publication-actions", () => ({
  prepareAgentCandidate: async () => {},
  testAgentCandidate: async () => {},
  reviewAgentTests: async () => {},
  publishAgentCandidate: async () => {},
  rollbackAgent: async () => {},
}));
const backend = vi.mocked(callAuthenticatedBackend);
const tenant = "019c2000-0000-7000-8000-000000000111";
const version = "019c2000-0000-7000-8000-000000000222";
const runId = "019c2000-0000-7000-8000-000000000333";
const account = "019c2000-0000-7000-8000-000000000444";
const state = {
  saved_revision: 3,
  candidates: [{ id: version, version_number: 1, state: "TEST" }],
  accounts: [
    {
      id: account,
      display_phone_number: "573000000001",
      status: "active",
      health_status: "HEALTHY",
    },
  ],
  bindings: [],
  blockers: [],
};
beforeEach(() => {
  backend.mockReset();
});

it("separates saved draft from active version and requires account selection", async () => {
  backend.mockResolvedValue(state);
  const markup = renderToStaticMarkup(
    await AgentPublication({ tenantId: tenant, step: "test" }),
  );
  expect(markup).toContain("Revisión guardada: 3");
  expect(markup).toContain("Ningún agente publicado");
  expect(markup).toContain("Preparar candidato");
  expect(markup).toContain("cuenta seleccionada explícitamente");
  expect(markup).not.toContain(`value="${account}" selected`);
});

it("shows reviewed answers safely and cannot publish failing checks", async () => {
  backend.mockImplementation(async (path) =>
    path.includes("/tests/")
      ? {
          id: runId,
          version_id: version,
          onboarding_revision: 3,
          is_current: true,
          approved: null,
          expires_at: "2099-01-01T00:00:00Z",
          result: {
            checks_passed: false,
            scenarios: [
              {
                key: "greeting",
                prompt: "Hola",
                response: "<script>bad</script>",
                passed: false,
                error_code: "runtime_error",
              },
            ],
          },
        }
      : state,
  );
  const markup = renderToStaticMarkup(
    await AgentPublication({ tenantId: tenant, step: "quality-gate", runId }),
  );
  expect(markup).toContain("&lt;script&gt;bad&lt;/script&gt;");
  expect(markup).not.toContain("<script>bad</script>");
  expect(markup).toContain("Las comprobaciones no pasaron");
  expect(markup).not.toContain("Publicar versión en WhatsApp");
});

it("marks pending tests as pending rather than successful", async () => {
  backend.mockImplementation(async (path) =>
    path.includes("/tests/")
      ? { id: runId, version_id: version, approved: null, result: null }
      : state,
  );
  const markup = renderToStaticMarkup(
    await AgentPublication({ tenantId: tenant, step: "test", runId }),
  );
  expect(markup).toContain("Pruebas pendientes");
  expect(markup).not.toContain("Publicar versión en WhatsApp");
});

it("renders publication only after reviewed passing evidence and disables unhealthy accounts", async () => {
  backend.mockImplementation(async (path) =>
    path.includes("/tests/")
      ? {
          id: runId,
          version_id: version,
          approved: true,
          onboarding_revision: 3,
          is_current: true,
          expires_at: "2099-01-01T00:00:00Z",
          result: { checks_passed: true, scenarios: [] },
        }
      : {
          ...state,
          accounts: [{ ...state.accounts[0], health_status: "UNKNOWN" }],
        },
  );
  const markup = renderToStaticMarkup(
    await AgentPublication({ tenantId: tenant, step: "production", runId }),
  );
  expect(markup).toContain("Publicar versión en WhatsApp");
  expect(markup).toContain(`disabled="" value="${account}"`);
  expect(markup).toContain("confirmPublish");
  expect(markup).not.toContain(`value="${account}" selected`);
});

it("does not call connection workflow when WhatsApp is already healthy", async () => {
  backend.mockResolvedValue(state);
  const markup = renderToStaticMarkup(
    await AgentPublication({ tenantId: tenant, step: "whatsapp" }),
  );
  expect(markup).toContain("No necesitas reconectar");
  expect(markup).not.toContain("Embedded Signup");
});

it("reports backend failure without exposing its internal details", async () => {
  backend.mockRejectedValue(new Error("private failure"));
  const markup = renderToStaticMarkup(
    await AgentPublication({ tenantId: tenant, step: "test" }),
  );
  expect(markup).toContain("No se pudo consultar");
  expect(markup).not.toContain("private failure");
});

it("does not offer publication for a previously approved stale run", async () => {
  backend.mockImplementation(async (path) =>
    path.includes("/tests/")
      ? {
          id: runId,
          version_id: version,
          onboarding_revision: 2,
          is_current: false,
          approved: true,
          expires_at: "2099-01-01T00:00:00Z",
          result: { checks_passed: true, scenarios: [] },
        }
      : state,
  );
  const markup = renderToStaticMarkup(
    await AgentPublication({ tenantId: tenant, step: "production", runId }),
  );
  expect(markup).toContain("otra revisión");
  expect(markup).not.toContain("Publicar versión en WhatsApp");
});
