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
const approvalRoutes = new Map();
const handoffConfigurations = new Map();
let calendarHealthAttempts = 0;
let onboardingConfigurationChanged = false;

const capabilityManifests = [
  {
    stable_name: "appointments",
    version: "1.0.0",
    intents: ["check_availability", "request_cancellation"],
    workflow: ["verify_identity", "confirm", "execute"],
    actions: [
      capabilityAction(
        "appointments.check_availability",
        "Check available appointment slots.",
        "LOW",
        0,
        false,
        false,
        ["calendar.check_availability"],
      ),
      capabilityAction(
        "appointments.request_cancellation",
        "Request cancellation through an approved backoffice route.",
        "HIGH",
        2,
        true,
        true,
        ["calendar.get_event"],
      ),
    ],
  },
  {
    stable_name: "orders",
    version: "1.0.0",
    intents: ["order_status", "request_cancellation"],
    workflow: ["verify_owner", "read_order", "execute_once"],
    actions: [
      capabilityAction(
        "orders.get_status",
        "Read a verified customer's order status.",
        "LOW",
        1,
        false,
        false,
        ["orders.get_status"],
      ),
      capabilityAction(
        "orders.request_order_cancellation",
        "Request order cancellation without promising its result.",
        "HIGH",
        2,
        true,
        true,
        ["orders.request_order_cancellation", "orders.get_status"],
      ),
    ],
  },
  {
    stable_name: "returns_claims",
    version: "1.0.0",
    intents: ["create_claim", "claim_status"],
    workflow: ["collect_evidence", "backoffice_review"],
    actions: [
      capabilityAction(
        "returns_claims.get_case_status",
        "Read a verified customer's case status.",
        "LOW",
        1,
        false,
        false,
        [],
        "none",
      ),
    ],
  },
];

const integrationConnections = [
  {
    id: "41000000-0000-4000-8000-000000000040",
    connector_name: "google_calendar",
    auth_kind: "OAUTH2",
    status: "REAUTH_REQUIRED",
    requested_scopes: ["calendar.events"],
    granted_scopes: ["calendar.events"],
    expires_at: null,
    health: {
      status: "REAUTH_REQUIRED",
      checked_at: now,
      error_code: "oauth_expired",
    },
  },
  {
    id: "42000000-0000-4000-8000-000000000040",
    connector_name: "google_sheets",
    auth_kind: "OAUTH2",
    status: "CONNECTED",
    requested_scopes: ["spreadsheets"],
    granted_scopes: ["spreadsheets"],
    expires_at: null,
    health: { status: "HEALTHY", checked_at: now, error_code: null },
  },
];

function capabilityAction(
  name,
  description,
  risk,
  requiredIdentityLevel,
  requiresConfirmation,
  requiresApproval,
  operations,
  requirementMode = "single_binding",
) {
  return {
    name,
    description,
    risk,
    required_identity_level: requiredIdentityLevel,
    requires_confirmation: requiresConfirmation,
    requires_approval: requiresApproval,
    required_connector_operations: operations,
    connector_requirement_mode: requirementMode,
  };
}

const onboardingSteps = [
  ["company", "Company", "/settings"],
  ["agent", "Agent", "/agent"],
  ["capabilities", "Capabilities", "/capabilities"],
  ["integrations", "Integrations", "/integrations"],
  ["knowledge-conflict-review", "Knowledge & Conflict Review", "/knowledge"],
  ["policies-identity", "Policies & Identity", "/capabilities"],
  ["human-operations", "Human Operations", "/settings"],
  ["approval-routes", "Approval Routes", "/capabilities"],
  ["whatsapp", "WhatsApp", "/whatsapp"],
  ["test", "Test", "/agent"],
  ["quality-gate", "Quality Gate", "/agent"],
  ["production", "Production", "/agent"],
];

function onboardingStatus(tenantId) {
  const steps = onboardingSteps.map(([slug, name, suffix], index) => {
    let status = index < 10 ? "COMPLETE" : "UNAVAILABLE";
    let blockers = [];
    if (slug === "test" && onboardingConfigurationChanged) {
      status = "STALE";
      blockers = [
        {
          code: "tested_candidate_stale",
          message: "A newer Agent Draft exists after the last tested version.",
        },
      ];
    }
    if (slug === "quality-gate") {
      blockers = [
        ...(onboardingConfigurationChanged
          ? [
              {
                code: "test_required",
                message: "Complete the current Test candidate first.",
              },
            ]
          : []),
        {
          code: "production_quality_gate_task_45_required",
          message:
            "Task 45 must persist exact-digest Production Quality Gate evidence.",
        },
      ];
    }
    if (slug === "production") {
      blockers = [
        {
          code: "quality_gate_required",
          message: "Production requires the unavailable Task 45 Quality Gate.",
        },
      ];
    }
    return {
      number: index + 1,
      slug,
      name,
      instructions: [`Complete the approved ${name} configuration.`],
      required_fields: [`${name} configuration`],
      validations: [`${name} validation is derived from saved domain facts.`],
      status,
      blockers,
      warnings: [],
      test_actions: [
        {
          label: `Review ${name}`,
          href: `/tenants/${tenantId}${suffix}`,
          available: status !== "UNAVAILABLE" && status !== "BLOCKED",
        },
      ],
      documentation: [
        {
          label: `${name} internal documentation`,
          href: "https://github.com/ZuvelAI/agents-factory/blob/main/docs/implementation/ms7-progress.md",
        },
      ],
    };
  });
  return {
    tenant_id: tenantId,
    agent_instance_id: "20000000-0000-4000-8000-000000000039",
    agent_version_id: "30000000-0000-4000-8000-000000000039",
    agent_version_number: onboardingConfigurationChanged ? 8 : 7,
    complete_steps: onboardingConfigurationChanged ? 9 : 10,
    current_step_slug: onboardingConfigurationChanged ? "test" : "quality-gate",
    classifications: [
      "STANDARD",
      "CUSTOM_CONNECTOR",
      "CUSTOM_WORKFLOW",
      "NEW_CAPABILITY",
    ],
    steps,
  };
}

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
      capabilities: [],
      permitted_tools: [],
      permitted_actions: [],
      connector_bindings: [],
      action_policies: [],
      human_operations: {
        version: "1.0.0",
        handoff_enabled: false,
        handoff_surface_available: false,
        awaiting_human_policy: "SILENT",
      },
      policy: { name: "platform_default", version: "1.0.0" },
      identity_policy: { name: "platform_default", version: "1.0.0" },
      approval_routes: { name: "standard", version: "1.0.0" },
    },
    compiled_spec: null,
    compiled_digest: null,
    created_at: now,
    updated_at: now,
  };
}

const seededEditor = createEditor(tenants[0], tenants[0].name);
seededEditor.editable_version.configuration.capabilities = [
  { name: "appointments", version: "1.0.0" },
  { name: "orders", version: "1.0.0" },
];
seededEditor.editable_version.configuration.permitted_tools =
  capabilityManifests
    .filter((manifest) => manifest.stable_name !== "returns_claims")
    .flatMap((manifest) => manifest.actions.map((action) => action.name));
seededEditor.editable_version.configuration.permitted_actions = [
  ...seededEditor.editable_version.configuration.permitted_tools,
];
seededEditor.editable_version.configuration.connector_bindings = [
  {
    binding_id: integrationConnections[1].id,
    connector: "google_sheets",
    connector_version: "1.0.0",
    operations: ["orders.get_status"],
  },
];
seededEditor.quick_options = ["Check availability", "Track an order"];
agents.set(tenants[0].id, seededEditor);

function saveConfigurationDraft(editor, configuration) {
  editor.editable_version = version(
    editor.editable_version.version_number + 1,
    configuration.persona.business_name,
    configuration,
  );
  return editor.editable_version;
}

function connectorCatalog() {
  const entries = [
    {
      connector_name: "google_calendar",
      display_name: "Google Calendar",
      available: true,
      availability: "AVAILABLE",
      auth_kind: "OAUTH2",
      required_scopes: ["calendar.events"],
      supported_operations: [
        "calendar.check_availability",
        "calendar.get_event",
      ],
      note: "Calendar access is granted by the tenant.",
    },
    {
      connector_name: "google_sheets",
      display_name: "Google Sheets",
      available: true,
      availability: "AVAILABLE",
      auth_kind: "OAUTH2",
      required_scopes: ["spreadsheets"],
      supported_operations: ["orders.get_status", "sheets.read_rows"],
      note: "Mapped sheets remain isolated from other provider failures.",
    },
    {
      connector_name: "woocommerce",
      display_name: "WooCommerce",
      available: true,
      availability: "AVAILABLE",
      auth_kind: "API_KEY",
      required_scopes: [],
      supported_operations: [
        "orders.get_status",
        "orders.request_order_cancellation",
      ],
      note: "Connect a tenant-owned WooCommerce store.",
    },
    {
      connector_name: "meta_whatsapp",
      display_name: "Meta WhatsApp",
      available: true,
      availability: "AVAILABLE",
      auth_kind: "META_EMBEDDED",
      required_scopes: [],
      supported_operations: [],
      note: "Connect through Meta Embedded Signup.",
    },
    {
      connector_name: "generic_rest_api",
      display_name: "Generic REST API",
      available: false,
      availability: "COMING_LATER",
      auth_kind: null,
      required_scopes: [],
      supported_operations: [],
      note: "Deferred to v1.1 Custom Onboarding Foundation.",
    },
    {
      connector_name: "hubspot",
      display_name: "HubSpot",
      available: false,
      availability: "COMING_LATER",
      auth_kind: null,
      required_scopes: [],
      supported_operations: [],
      note: "Provider adapter is not included in v1.",
    },
  ];
  return entries.map((entry) => ({
    ...entry,
    connections: integrationConnections.filter(
      (connection) => connection.connector_name === entry.connector_name,
    ),
  }));
}

createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  if (
    request.method === "POST" &&
    url.pathname === "/__test/onboarding/upstream-change"
  ) {
    onboardingConfigurationChanged = true;
    json(response, 204, null);
    return;
  }
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

  if (request.method === "GET" && url.pathname === "/admin/capabilities") {
    json(response, 200, capabilityManifests);
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

  const onboardingMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/onboarding$/,
  );
  if (onboardingMatch && request.method === "GET") {
    const tenant = tenants.find((item) => item.id === onboardingMatch[1]);
    if (!tenant) {
      json(response, 404, { error: "not_found" });
      return;
    }
    json(response, 200, onboardingStatus(tenant.id));
    return;
  }

  const whatsappMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/whatsapp$/,
  );
  if (whatsappMatch && request.method === "GET") {
    json(response, 200, []);
    return;
  }

  const catalogMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/integrations\/catalog$/,
  );
  if (catalogMatch && request.method === "GET") {
    json(response, 200, connectorCatalog());
    return;
  }

  const connectionActionMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/integrations\/connections\/([^/]+)\/(health|refresh|revoke)$/,
  );
  if (connectionActionMatch && request.method === "POST") {
    const connection = integrationConnections.find(
      (item) => item.id === connectionActionMatch[2],
    );
    if (!connection) {
      json(response, 404, { error: "not_found" });
      return;
    }
    const action = connectionActionMatch[3];
    if (action === "refresh") {
      connection.status = "CONNECTED";
      connection.health = {
        status: "UNKNOWN",
        checked_at: null,
        error_code: null,
      };
    } else if (action === "revoke") {
      connection.status = "REVOKED";
      connection.health = {
        status: "UNKNOWN",
        checked_at: now,
        error_code: null,
      };
    } else if (connection.connector_name === "google_calendar") {
      calendarHealthAttempts += 1;
      connection.health =
        calendarHealthAttempts === 1
          ? {
              status: "ERROR",
              checked_at: now,
              error_code: "provider_unavailable",
            }
          : { status: "HEALTHY", checked_at: now, error_code: null };
    }
    json(response, 200, connection);
    return;
  }

  const approvalRoutesMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/approvals\/routes$/,
  );
  if (approvalRoutesMatch && request.method === "GET") {
    json(response, 200, approvalRoutes.get(approvalRoutesMatch[1]) ?? []);
    return;
  }
  if (approvalRoutesMatch && request.method === "PUT") {
    const body = await readJson(request);
    const routes = approvalRoutes.get(approvalRoutesMatch[1]) ?? [];
    const existing = routes.find(
      (item) => item.configuration.action === body.configuration.action,
    );
    if ((existing?.revision ?? 0) !== body.expected_revision) {
      problem(response, 409, "approval_route_stale", "Reload before saving.");
      return;
    }
    const route = {
      id: existing?.id ?? "43000000-0000-4000-8000-000000000040",
      tenant_id: approvalRoutesMatch[1],
      revision: (existing?.revision ?? 0) + 1,
      configuration: {
        expires_minutes: 1440,
        otp_seconds: 600,
        otp_max_attempts: 5,
        otp_max_sends: 3,
        otp_cooldown_seconds: 60,
        ...body.configuration,
      },
      digest: "a".repeat(64),
    };
    if (existing) Object.assign(existing, route);
    else routes.push(route);
    approvalRoutes.set(approvalRoutesMatch[1], routes);
    json(response, 200, route);
    return;
  }

  const handoffConfigurationsMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/handoffs\/configurations$/,
  );
  if (handoffConfigurationsMatch && request.method === "GET") {
    json(
      response,
      200,
      handoffConfigurations.get(handoffConfigurationsMatch[1]) ?? [],
    );
    return;
  }

  const handoffSurfacesMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/handoffs\/surfaces$/,
  );
  if (handoffSurfacesMatch && request.method === "GET") {
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

  const configurationDraftMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/agent-instances\/([^/]+)\/(capability|policy|connector-binding|human-operations|approval-route)-drafts$/,
  );
  if (configurationDraftMatch && request.method === "POST") {
    const editor = agents.get(configurationDraftMatch[1]);
    if (!editor || editor.instance.id !== configurationDraftMatch[2]) {
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
    const kind = configurationDraftMatch[3];
    const configuration = structuredClone(
      editor.editable_version.configuration,
    );
    if (kind === "capability") {
      const manifests = body.capability_names.map((name) =>
        capabilityManifests.find((manifest) => manifest.stable_name === name),
      );
      if (manifests.some((manifest) => !manifest)) {
        problem(
          response,
          409,
          "capability_unavailable",
          "Capability unavailable.",
        );
        return;
      }
      configuration.capabilities = manifests.map((manifest) => ({
        name: manifest.stable_name,
        version: manifest.version,
      }));
      configuration.permitted_actions = manifests.flatMap((manifest) =>
        manifest.actions.map((action) => action.name),
      );
      configuration.permitted_tools = [...configuration.permitted_actions];
      configuration.action_policies = configuration.action_policies.filter(
        (policy) => configuration.permitted_actions.includes(policy.action),
      );
    } else if (kind === "policy") {
      for (const policy of body.policies) {
        const definition = capabilityManifests
          .flatMap((manifest) => manifest.actions)
          .find((action) => action.name === policy.action);
        if (
          !definition ||
          policy.identity_level < definition.required_identity_level ||
          (definition.requires_confirmation && !policy.confirmation_required) ||
          (definition.requires_approval && !policy.approval_required)
        ) {
          problem(
            response,
            409,
            "policy_weakens_platform_minimum",
            "Tenant policy cannot weaken a platform minimum.",
          );
          return;
        }
      }
      configuration.action_policies = body.policies;
      configuration.policy = {
        name: "tenant_action_policy",
        version: String(editor.editable_version.version_number + 1),
      };
      configuration.identity_policy = {
        name: "tenant_identity_policy",
        version: String(editor.editable_version.version_number + 1),
      };
    } else if (kind === "connector-binding") {
      const connection = integrationConnections.find(
        (item) => item.id === body.connection_id,
      );
      const catalog = connectorCatalog().find(
        (item) => item.connector_name === body.connector_name,
      );
      if (
        !connection ||
        connection.status !== "CONNECTED" ||
        !catalog?.available ||
        !body.operations.every((operation) =>
          catalog.supported_operations.includes(operation),
        )
      ) {
        problem(
          response,
          409,
          "connector_operation_unsupported",
          "The connector operation is unsupported.",
        );
        return;
      }
      configuration.connector_bindings =
        configuration.connector_bindings.filter(
          (binding) => binding.binding_id !== body.connection_id,
        );
      configuration.connector_bindings.push({
        binding_id: body.connection_id,
        connector: body.connector_name,
        connector_version: "1.0.0",
        operations: body.operations,
      });
    } else if (kind === "human-operations") {
      if (
        body.handoff_enabled &&
        (handoffConfigurations.get(configurationDraftMatch[1]) ?? []).every(
          (item) => !item.configuration.enabled || !item.configuration.surface,
        )
      ) {
        problem(response, 409, "human_surface_required", "Surface required.");
        return;
      }
      configuration.human_operations = {
        ...configuration.human_operations,
        version: String(editor.editable_version.version_number + 1),
        handoff_enabled: body.handoff_enabled,
        handoff_surface_available: body.handoff_enabled,
      };
    } else {
      configuration.approval_routes = {
        name: "standard",
        version: String(body.route_revision),
      };
    }
    json(response, 201, saveConfigurationDraft(editor, configuration));
    return;
  }

  json(response, 404, { error: "not_found" });
}).listen(port, "127.0.0.1");
