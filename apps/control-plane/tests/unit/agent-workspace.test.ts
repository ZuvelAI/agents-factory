import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";
import CompaniesPage from "../../app/(authenticated)/tenants/page";
import CompanyPage from "../../app/(authenticated)/tenants/[tenantId]/page";
import { callAuthenticatedBackend } from "../../lib/api";

vi.mock("../../lib/api", () => ({ callAuthenticatedBackend: vi.fn() }));
const backend = vi.mocked(callAuthenticatedBackend);
const tenant = "019c2000-0000-7000-8000-000000000102";
const agent = "019c2000-0000-7000-8000-000000000501";
const summary = {
  id: agent,
  tenant_id: tenant,
  display_name: "Asistente comercial",
  published_name: null,
  purpose: null,
  published_version_id: null,
  draft_version_id: agent,
  has_pending_changes: true,
  execution_status: "unassigned",
  status_checked_at: null,
  channel_accounts: [],
};
beforeEach(() => {
  backend.mockReset();
});

it("shows real counts and UUID links without pretending drafts are active", async () => {
  backend.mockResolvedValue({
    items: [{ id: tenant, name: "Zuvel", agent_count: 4, agents: [summary] }],
    next_cursor: null,
  });
  const html = renderToStaticMarkup(await CompaniesPage({}));
  expect(html).toContain("4 agentes");
  expect(html).toContain(`/tenants/${tenant}`);
  expect(html).toContain("Asistente comercial");
  expect(html).toContain("Sin canal");
  expect(html).not.toContain("4 activos");
  expect(html).not.toContain("Abrir onboarding");
});

it("distinguishes failure from an empty company list", async () => {
  backend.mockRejectedValue(new Error("private diagnostic"));
  const html = renderToStaticMarkup(await CompaniesPage({}));
  expect(html).toContain("No pudimos cargar las empresas");
  expect(html).not.toContain("private diagnostic");
  expect(html).not.toContain("No hay empresas");
});

it("shows an honest zero-agent company and missing metrics without inventing totals", async () => {
  backend.mockResolvedValue({
    items: [
      { id: tenant, name: "Empresa sin agentes", agent_count: 0, agents: [] },
    ],
    next_cursor: null,
  });
  const html = renderToStaticMarkup(await CompaniesPage({}));
  expect(html).toContain("Sin agentes");
  expect(html).not.toContain("Agentes activos");
  backend.mockResolvedValue({
    items: [{ id: tenant, name: "Malformada", agents: [] }],
    next_cursor: null,
  });
  expect(renderToStaticMarkup(await CompaniesPage({}))).toContain(
    "No pudimos cargar las empresas",
  );
});

it("opens the selected company and escapes long names", async () => {
  backend.mockImplementation(async (path) =>
    path.endsWith("/agents")
      ? { items: [summary], next_cursor: null }
      : { items: [], next_cursor: null },
  );
  const html = renderToStaticMarkup(
    await CompanyPage({ params: Promise.resolve({ tenantId: tenant }) }),
  );
  expect(html).toContain(`/tenants/${tenant}/agents/${agent}`);
  expect(html).toContain(`tenant=${tenant}`);
  expect(html).toContain("Nuevo agente");
  expect(html).toContain("disabled");
});

it("rejects invalid path identifiers before backend requests", async () => {
  const html = renderToStaticMarkup(
    await CompanyPage({ params: Promise.resolve({ tenantId: "../private" }) }),
  );
  expect(html).toContain("Empresa no disponible");
  expect(backend).not.toHaveBeenCalled();
});
