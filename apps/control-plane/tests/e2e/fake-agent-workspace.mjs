// Synthetic UI fixture only. Database behavior is tested separately against PostgreSQL.
export const workspaceTenant = "019c2000-0000-7000-8000-000000000102";
import { audioMessages } from "./fake-audio-conversations.mjs";
const other = "019c2000-0000-7000-8000-000000000103";
const empty = "019c2000-0000-7000-8000-000000000104";
function agent(id, tenant, name) {
  return {
    id,
    tenant_id: tenant,
    display_name: name,
    published_name: null,
    purpose: null,
    published_version_id: null,
    draft_version_id: id,
    has_pending_changes: true,
    execution_status: "unassigned",
    status_checked_at: null,
    channel_accounts: [],
  };
}
const first = agent(
  "019c2000-0000-7000-8000-000000000501",
  workspaceTenant,
  "Asistente comercial",
);
const second = agent(
  "019c2000-0000-7000-8000-000000000502",
  workspaceTenant,
  "Soporte al cliente",
);
const third = agent(
  "019c2000-0000-7000-8000-000000000503",
  other,
  "Seguimiento comercial",
);
const companies = [
  {
    id: workspaceTenant,
    name: "Zuvel",
    agent_count: 2,
    agents: [first, second],
  },
  { id: other, name: "Empresa homónima", agent_count: 1, agents: [third] },
  { id: empty, name: "Empresa homónima", agent_count: 0, agents: [] },
];
export function handleAgentWorkspace(request, response, url, json) {
  if (url.pathname === "/admin/agent-workspace/company-options") {
    json(response, 200, {
      items: companies.map(({ id, name }) => ({ id, name })),
      next_cursor: null,
    });
    return true;
  }
  const root = "/admin/agent-workspace/companies";
  if (!url.pathname.startsWith(root)) return false;
  if (request.method !== "GET") {
    json(response, 405, {});
    return true;
  }
  if (url.pathname === root) {
    const query = url.searchParams.get("query") ?? "";
    if (query === "fallo-controlado") {
      json(response, 503, {});
      return true;
    }
    json(response, 200, {
      items: companies.filter((c) =>
        c.name.toLowerCase().includes(query.toLowerCase()),
      ),
      next_cursor: null,
    });
    return true;
  }
  if (
    url.pathname.match(/^\/admin\/agent-workspace\/companies\/[^/]+\/accounts$/)
  ) {
    json(response, 200, {
      items: [
        {
          account_id: "019c2000-0000-7000-8000-000000000202",
          display_number: "+573000000000",
          version_id: null,
          connection_status: "unknown",
          checked_at: null,
        },
      ],
      next_cursor: null,
    });
    return true;
  }
  const convo = url.pathname.match(
    /^\/admin\/agent-workspace\/companies\/([^/]+)\/conversations(?:\/([^/]+)(?:\/messages)?)?$/,
  );
  if (convo) {
    const conversation = "019c2000-0000-7000-8000-000000000303";
    const account = "019c2000-0000-7000-8000-000000000202";
    if (convo[1] !== workspaceTenant) {
      json(response, 200, { items: [], next_cursor: null });
      return true;
    }
    if (convo[2]) {
      if (convo[2] !== conversation) {
        json(response, 404, {});
        return true;
      }
      if (!url.pathname.endsWith("/messages")) {
        const selected = url.searchParams.get("agent_id");
        if (selected && selected !== first.id) {
          json(response, 404, {});
          return true;
        }
        json(response, 200, {
          id: conversation,
          account_id: account,
          customer_wa_id: "Contacto de prueba",
          control_state: "AI_ACTIVE",
          updated_at: "2026-10-14T15:00:00Z",
          last_activity_at: "2026-10-15T15:00:00Z",
          agent_ids: [first.id],
        });
        return true;
      }
      json(response, 200, {
        items: url.searchParams.get("cursor")?.startsWith("audio-")
          ? audioMessages(
              url.searchParams.get("cursor") === "audio-pending"
                ? "QUEUED"
                : "READY",
            )
          : [
              {
                id: first.id,
                arrival_sequence: 1,
                direction: "outbound",
                message_type: "text",
                text: "En Zuvel te ayudamos a mejorar tus ventas.",
                created_at: "2026-10-14T15:00:00Z",
                agent_id: first.id,
                agent_spec_id: first.id,
                delivery_status: "DELIVERED",
              },
            ],
        next_cursor: null,
      });
      return true;
    }
    const selected = url.searchParams.get("agent_id");
    json(response, 200, {
      items:
        url.searchParams.get("cursor") === "off-page" ||
        (selected && selected !== first.id)
          ? []
          : [
              {
                id: conversation,
                account_id: account,
                customer_wa_id: "Contacto de prueba",
                control_state: "AI_ACTIVE",
                updated_at: "2026-10-14T15:00:00Z",
                agent_ids: [first.id],
              },
            ],
      next_cursor: null,
    });
    return true;
  }
  const match = url.pathname.match(
    /^\/admin\/agent-workspace\/companies\/([^/]+)\/agents(?:\/([^/]+))?$/,
  );
  const company = companies.find((c) => c.id === match?.[1]);
  if (!company) {
    json(response, 404, {});
    return true;
  }
  if (!match[2]) {
    json(response, 200, {
      items: company.agents,
      next_cursor: null,
      company_name: company.name,
    });
    return true;
  }
  const selected = company.agents.find((a) => a.id === match[2]);
  if (selected) {
    const config = {
      name: selected.display_name,
      purpose: null,
      tone: null,
      instructions: "Orienta sobre los servicios de Zuvel.",
      model: "gpt-6-luna",
      knowledge_summary: "Análisis de datos para toma de decisiones.",
      capabilities: [],
      integrations: [
        {
          key: "crm",
          label: "CRM",
          availability: "unavailable",
          enabled: false,
          reason: "Conector no implementado",
        },
      ],
    };
    json(response, 200, {
      summary: {
        ...selected,
        published_version_id: selected.id,
        published_name: selected.display_name,
      },
      published: config,
      draft: {
        ...config,
        name: "Nombre pendiente",
        instructions: "Cambio de instrucciones sin publicar",
      },
      unavailable_sections: [],
    });
    return true;
  }
  json(response, 404, {});
  return true;
}
