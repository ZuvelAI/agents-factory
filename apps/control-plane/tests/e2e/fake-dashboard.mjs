import { createServer } from "node:http";

const port = Number(process.env.FAKE_DASHBOARD_PORT ?? "8000");
const now = "2026-09-01T15:00:00Z";
const tenants = [
  {
    id: "019c2000-0000-7000-8000-000000000101",
    slug: "whatsapp-test",
    name: "WhatsApp Test",
    legal_name: "WhatsApp Test SAS",
    industry: "Services",
    timezone: "America/Bogota",
    locale: "es-CO",
    status: "active",
    revision: 1,
    created_at: now,
    updated_at: now,
  },
];
const agents = new Map();

function json(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(body));
}

function problem(response, status, code, detail) {
  response.writeHead(status, {
    "content-type": "application/problem+json",
    "cache-control": "no-store",
  });
  response.end(
    JSON.stringify({
      type: `https://agents-factory.dev/problems/${code}`,
      title: "Request conflict",
      status,
      detail,
      code,
      correlation_id: "10000000-0000-4000-8000-000000000038",
    }),
  );
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function createEditor(tenant, businessName) {
  return {
    instance: {
      id: `20000000-0000-4000-8000-${tenant.id.slice(-12)}`,
      tenant_id: tenant.id,
      product: "Agent Customer Service",
      created_at: now,
      updated_at: now,
    },
    editable_version: version(1, businessName),
    production_version: null,
    quick_options: [],
  };
}

function version(number, businessName, configuration) {
  return {
    id: `30000000-0000-4000-8000-${String(number).padStart(12, "0")}`,
    tenant_id: "unused-by-ui",
    agent_instance_id: "unused-by-ui",
    version_number: number,
    state: "DRAFT",
    based_on_version_id: number === 1 ? null : "previous",
    configuration: configuration ?? {
      persona: {
        business_name: businessName,
        agent_name: null,
        tone: "Cercano y claro",
        formality: "Neutral",
        brand_vocabulary: [],
        greeting: "¡Hola! ¿En qué puedo ayudarte?",
      },
      language: {
        supported_locales: ["es-CO", "en-US"],
        default_locale: "es-CO",
      },
    },
    compiled_spec: null,
    compiled_digest: null,
    created_at: now,
    updated_at: now,
  };
}

createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  if (!request.headers.authorization?.startsWith("Bearer ")) {
    json(response, 401, { error: "authentication_required" });
    return;
  }
  if (request.method === "GET" && url.pathname === "/admin/dashboard") {
    json(response, 200, {
      generated_at: "2026-09-01T15:00:00Z",
      usage_period_start: "2026-08-02T15:00:00Z",
      coverage: { tenant_count: 3, included_tenants: 3, complete: true },
      platform: {
        state: "healthy",
        services: [
          { name: "Control API", state: "healthy" },
          { name: "Data service", state: "healthy" },
          { name: "Work coordination", state: "healthy" },
        ],
      },
      agents: {
        configured: 4,
        operating: 3,
        state: "attention",
        freshness: "fresh",
      },
      operations: {
        work_items_requiring_attention: 2,
        state: "attention",
        freshness: "fresh",
      },
      cases: {
        critical_overdue: 1,
        state: "attention",
        freshness: "fresh",
      },
      integrations: {
        configured: 5,
        healthy: 3,
        requiring_attention: 1,
        unknown: 1,
        state: "unknown",
        freshness: "stale",
        last_checked_at: "2026-08-30T10:00:00Z",
      },
      usage: {
        events: 128,
        model_tokens: "24100",
        messages: "328",
        external_requests: "410",
        tool_calls: "92",
        known_costs: [{ currency: "USD", amount: "12.34" }],
        unknown_cost_events: 7,
        state: "unknown",
        freshness: "fresh",
        latest_at: "2026-09-01T14:58:00Z",
      },
    });
    return;
  }

  if (request.method === "GET" && url.pathname === "/admin/tenants") {
    json(response, 200, tenants);
    return;
  }

  if (request.method === "POST" && url.pathname === "/admin/tenants") {
    const body = await readJson(request);
    const tenant = {
      id: "019d0000-0000-7000-8000-000000000038",
      slug: body.slug,
      name: body.name,
      legal_name: body.legal_name,
      industry: body.industry,
      timezone: body.timezone,
      locale: body.locale,
      status: "active",
      revision: 1,
      created_at: now,
      updated_at: now,
    };
    const existing = tenants.findIndex((item) => item.id === tenant.id);
    if (existing >= 0) tenants.splice(existing, 1);
    tenants.push(tenant);
    agents.delete(tenant.id);
    json(response, 201, tenant);
    return;
  }

  const tenantMatch = url.pathname.match(/^\/admin\/tenants\/([^/]+)$/);
  if (tenantMatch && request.method === "GET") {
    const tenant = tenants.find((item) => item.id === tenantMatch[1]);
    if (!tenant) {
      json(response, 404, { error: "not_found" });
      return;
    }
    json(response, 200, tenant);
    return;
  }

  if (tenantMatch && request.method === "PUT") {
    const tenant = tenants.find((item) => item.id === tenantMatch[1]);
    if (!tenant) {
      json(response, 404, { error: "not_found" });
      return;
    }
    const body = await readJson(request);
    if (body.expected_revision !== tenant.revision) {
      problem(response, 409, "tenant_profile_stale", "Reload before saving.");
      return;
    }
    Object.assign(tenant, {
      name: body.name,
      legal_name: body.legal_name,
      industry: body.industry,
      timezone: body.timezone,
      locale: body.locale,
      revision: tenant.revision + 1,
      updated_at: now,
    });
    json(response, 200, tenant);
    return;
  }

  const whatsappMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/whatsapp$/,
  );
  if (whatsappMatch && request.method === "GET") {
    json(response, 200, []);
    return;
  }

  const currentAgentMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/agent-instances\/current$/,
  );
  if (currentAgentMatch && request.method === "GET") {
    json(response, 200, agents.get(currentAgentMatch[1]) ?? null);
    return;
  }

  const createAgentMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/agent-instances\/customer-service$/,
  );
  if (createAgentMatch && request.method === "POST") {
    const tenant = tenants.find((item) => item.id === createAgentMatch[1]);
    if (!tenant) {
      json(response, 404, { error: "not_found" });
      return;
    }
    const body = await readJson(request);
    const editor = createEditor(tenant, body.business_name);
    agents.set(tenant.id, editor);
    json(response, 201, {
      instance: editor.instance,
      draft: editor.editable_version,
    });
    return;
  }

  const presentationMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/agent-instances\/([^/]+)\/presentation-drafts$/,
  );
  if (presentationMatch && request.method === "POST") {
    const editor = agents.get(presentationMatch[1]);
    if (!editor || editor.instance.id !== presentationMatch[2]) {
      json(response, 404, { error: "not_found" });
      return;
    }
    const body = await readJson(request);
    if (body.expected_version_id !== editor.editable_version.id) {
      problem(
        response,
        409,
        "agent_spec_stale_write",
        "The Agent Draft changed. Reload before saving.",
      );
      return;
    }
    const configuration = structuredClone(
      editor.editable_version.configuration,
    );
    for (const field of [
      "agent_name",
      "tone",
      "formality",
      "brand_vocabulary",
      "greeting",
    ]) {
      if (Object.hasOwn(body, field))
        configuration.persona[field] = body[field];
    }
    if (Object.hasOwn(body, "supported_locales")) {
      configuration.language.supported_locales = body.supported_locales;
    }
    if (Object.hasOwn(body, "default_locale")) {
      configuration.language.default_locale = body.default_locale;
    }
    editor.editable_version = version(
      editor.editable_version.version_number + 1,
      configuration.persona.business_name,
      configuration,
    );
    json(response, 201, editor.editable_version);
    return;
  }

  json(response, 404, { error: "not_found" });
}).listen(port, "127.0.0.1");
