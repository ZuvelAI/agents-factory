import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";
import CompaniesPage from "../../app/(authenticated)/tenants/page";
import CompanyPage from "../../app/(authenticated)/tenants/[tenantId]/page";
import AgentPage from "../../app/(authenticated)/tenants/[tenantId]/agents/[agentId]/page";
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

it("keeps published content apart from draft and makes unavailable tools explicit", async () => {
  const config = {
    name: "Agente publicado",
    purpose: null,
    tone: null,
    instructions: "Instrucciones publicadas",
    model: "gpt-6-luna",
    knowledge_summary: "Servicios aprobados",
    capabilities: [],
    integrations: [
      {
        key: "crm",
        label: "CRM",
        availability: "unavailable",
        enabled: false,
        reason: "Conector todavía no implementado",
      },
    ],
  };
  backend.mockResolvedValue({
    summary: {
      ...summary,
      published_name: "Agente publicado",
      published_version_id: tenant,
    },
    published: config,
    draft: { ...config, name: "Nombre nuevo", instructions: "Solo borrador" },
    unavailable_sections: [],
  });
  const html = renderToStaticMarkup(
    await AgentPage({
      params: Promise.resolve({ tenantId: tenant, agentId: agent }),
    }),
  );
  expect(html).toContain("Configuración publicada");
  expect(html).toContain("Instrucciones publicadas");
  expect(html).toContain("Borrador sin publicar");
  expect(html).toContain("Solo borrador");
  expect(html).toContain("Conector todavía no implementado");
  expect(html).not.toContain("CRM · Activo");
  expect(html).toContain("No hay capacidades declaradas");
});

it("shows a draft-only agent without promising knowledge ingestion or testing", async () => {
  backend.mockResolvedValue({
    summary,
    published: null,
    draft: {
      name: "Agente",
      purpose: null,
      tone: null,
      instructions: null,
      model: null,
      knowledge_summary: null,
      capabilities: [],
      integrations: [],
    },
    unavailable_sections: [],
  });
  const html = renderToStaticMarkup(
    await AgentPage({
      params: Promise.resolve({ tenantId: tenant, agentId: agent }),
    }),
  );
  expect(html).toContain("Este agente aún no tiene una versión publicada");
  expect(html).toContain("No disponible en esta versión");
  expect(html).toContain("Pruebas interactivas en la siguiente entrega");
  expect(html).not.toContain("Escanear código QR");
});

it("rejects an agent response belonging to another company", async () => {
  backend.mockResolvedValue({
    summary: { ...summary, tenant_id: agent },
    published: null,
    draft: null,
    unavailable_sections: [],
  });
  const html = renderToStaticMarkup(
    await AgentPage({
      params: Promise.resolve({ tenantId: tenant, agentId: agent }),
    }),
  );
  expect(html).toContain("Agente no disponible");
  expect(html).not.toContain("Asistente comercial");
});

it("shows divergent account configurations instead of one common active version", async () => {
  const config = {
    name: "Zuvel",
    purpose: null,
    tone: null,
    instructions: "Última publicada",
    model: "gpt-6-luna",
    knowledge_summary: null,
    capabilities: [],
    integrations: [],
  };
  backend.mockResolvedValue({
    summary: { ...summary, published_version_id: tenant, channel_accounts: [] },
    published: config,
    draft: null,
    unavailable_sections: [],
    channel_versions: [
      {
        version_id: tenant,
        account_ids: [tenant],
        configuration: {
          ...config,
          instructions: "Número A conserva versión anterior",
        },
      },
      {
        version_id: agent,
        account_ids: [agent],
        configuration: {
          ...config,
          instructions: "Número B utiliza versión nueva",
        },
      },
    ],
  });
  const html = renderToStaticMarkup(
    await AgentPage({
      params: Promise.resolve({ tenantId: tenant, agentId: agent }),
    }),
  );
  expect(html).toContain("Versiones asignadas por canal");
  expect(html).toContain("Número A conserva versión anterior");
  expect(html).toContain("Número B utiliza versión nueva");
  expect(html).toContain("Última publicación registrada");
});
