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
let knowledgeEmbeddingsReady = false;
let knowledgeSequence = 10;
const productionConnectorCalls = 0;

const knowledgeWorkspace = {
  sources: [
    {
      source: knowledgeSource(
        "50000000-0000-4000-8000-000000000001",
        "Published business profile",
        "WEBSITE",
        "AUTHORITATIVE",
        { url: "https://example.test/business" },
      ),
      latest_ingestion: knowledgeIngestion(
        "51000000-0000-4000-8000-000000000001",
        "50000000-0000-4000-8000-000000000001",
        3,
      ),
    },
  ],
  proposals: [
    knowledgeProposal(
      "52000000-0000-4000-8000-000000000001",
      "50000000-0000-4000-8000-000000000001",
      "FACT",
      {
        source_id: "50000000-0000-4000-8000-000000000001",
        authority: "AUTHORITATIVE",
        key: "business.hours",
        kind: "BUSINESS_HOURS",
        value: { open: "09:00", close: "17:00" },
        locator: { path: "/business", section: "hours" },
        content_digest: "c".repeat(64),
      },
    ),
    knowledgeProposal(
      "52000000-0000-4000-8000-000000000002",
      "50000000-0000-4000-8000-000000000001",
      "DOCUMENT",
      {
        source_id: "50000000-0000-4000-8000-000000000001",
        authority: "AUTHORITATIVE",
        category: "POLICY",
        title: "Outdated returns note",
        text: "Returns are accepted for five days.",
        locator: { path: "/business", section: "returns" },
        content_digest: "d".repeat(64),
      },
    ),
    knowledgeProposal(
      "52000000-0000-4000-8000-000000000003",
      "50000000-0000-4000-8000-000000000001",
      "DOCUMENT",
      {
        source_id: "50000000-0000-4000-8000-000000000001",
        authority: "AUTHORITATIVE",
        category: "FAQ",
        title: "Delivery coverage",
        text: "Delivery is available in Bogota.",
        locator: { path: "/business", section: "delivery" },
        content_digest: "e".repeat(64),
      },
    ),
  ],
  conflicts: [
    {
      id: "53000000-0000-4000-8000-000000000001",
      proposal_id: "52000000-0000-4000-8000-000000000001",
      source_id: "50000000-0000-4000-8000-000000000001",
      fact_key: "business.hours",
      critical: true,
      proposed_authority: "AUTHORITATIVE",
      existing_authority: "AUTHORITATIVE",
      state: "OPEN",
      resolution: null,
      details: { message: "Two authoritative values disagree." },
      created_at: now,
    },
  ],
  diffs: [
    {
      id: "54000000-0000-4000-8000-000000000001",
      source_id: "50000000-0000-4000-8000-000000000001",
      ingestion_id: "51000000-0000-4000-8000-000000000001",
      draft_version_id: "55000000-0000-4000-8000-000000000002",
      previous_digest: "a".repeat(64),
      current_digest: "b".repeat(64),
      state: "DETECTED",
      summary: { message: "Business hours and policy content changed." },
      created_at: now,
    },
  ],
  versions: [
    knowledgeVersion(2, "DRAFT", null, "b".repeat(64)),
    knowledgeVersion(1, "PRODUCTION", "a".repeat(64), "a".repeat(64)),
  ],
  production_blocker_code: "production_quality_gate_required",
  production_blocker:
    "Production requires the full Task 45 Quality Gate for the exact Knowledge digest.",
};

function knowledgeSource(id, name, sourceType, authority, configuration) {
  return {
    id,
    tenant_id: tenants[0].id,
    name,
    source_type: sourceType,
    authority,
    configuration,
    created_at: now,
  };
}

function knowledgeIngestion(id, sourceId, proposedArtifactCount = 0) {
  return {
    id,
    tenant_id: tenants[0].id,
    source_id: sourceId,
    state: "SUCCEEDED",
    content_digest: "b".repeat(64),
    storage_path: `private/${sourceId}`,
    proposed_artifact_count: proposedArtifactCount,
    error_code: null,
    created_at: now,
    updated_at: now,
    completed_at: now,
  };
}

function knowledgeProposal(id, sourceId, artifactType, payload) {
  return {
    id,
    tenant_id: tenants[0].id,
    ingestion_artifact_id: id.replace("5200", "5210"),
    ingestion_id: "51000000-0000-4000-8000-000000000001",
    source_id: sourceId,
    revision: 1,
    artifact_type: artifactType,
    state: "PROPOSED",
    proposed_payload: payload,
    decision_payload: null,
    proposed_by: "NORMALIZER",
    model_metadata: {},
    content_digest: payload.content_digest,
    decided_by_admin_id: null,
  };
}

function knowledgeVersion(number, state, digest, candidateDigest) {
  return {
    version: {
      id: `55000000-0000-4000-8000-${String(number).padStart(12, "0")}`,
      tenant_id: tenants[0].id,
      name: `Client Knowledge v${number}`,
      version_number: number,
      state,
      digest,
      based_on_version_id:
        number === 1
          ? null
          : `55000000-0000-4000-8000-${String(number - 1).padStart(12, "0")}`,
      created_at: now,
      updated_at: now,
    },
    structured_fact_count: 1,
    document_count: 2,
    candidate_digest: candidateDigest,
    v0_evaluation: state === "TEST" ? "PASSED" : "NOT_RUN",
    v0_passed_cases: state === "TEST" ? 3 : 0,
    v0_failed_cases: 0,
  };
}

const reviewedConversationId = "60000000-0000-4000-8000-000000000001";
const conversationCategories = [
  "AI_RESOLVED",
  "HUMAN_HANDOFF",
  "TOOL_FAILURE",
  "POLICY_VIOLATION",
  "COMPLAINT",
  "HIGH_COST",
  "FLAGGED",
];
const conversationLabels = [
  "CORRECT",
  "INCORRECT",
  "UNSAFE",
  "KNOWLEDGE_PROBLEM",
  "INTEGRATION_PROBLEM",
  "MODEL_REASONING_PROBLEM",
];
const conversationReviewState = {
  id: "61000000-0000-4000-8000-000000000001",
  conversation_id: reviewedConversationId,
  revision: 1,
  categories: [...conversationCategories],
  labels: ["INCORRECT"],
  note: "Order cancellation response needs review.",
  reviewed_by_admin_id: "10000000-0000-4000-8000-000000000001",
  updated_at: now,
};
const evalCaseDrafts = [];
const conversationMessages = [
  {
    id: "62000000-0000-4000-8000-000000000001",
    direction: "inbound",
    sender_type: "customer",
    message_type: "text",
    text: "Cancel order 1042 and email me at customer@example.test.",
    occurred_at: now,
    agent_spec_id: null,
    agent_spec_version: null,
    runtime_metadata: {},
  },
  {
    id: "62000000-0000-4000-8000-000000000002",
    direction: "outbound",
    sender_type: "ai",
    message_type: "text",
    text: "Your cancellation request was submitted for review.",
    occurred_at: now,
    agent_spec_id: "30000000-0000-4000-8000-000000000039",
    agent_spec_version: "7",
    runtime_metadata: {
      agent_spec_digest: "9".repeat(64),
      model: "gpt-5.6-luna",
      tool_calls: [
        {
          tool_name: "orders.request_order_cancellation",
          arguments: { order_reference: "[anonymized]" },
          output: { status: "review_required" },
        },
      ],
      usage: { total_tokens: 84 },
    },
  },
];

function conversationWorkspace(category) {
  const included =
    !category || conversationReviewState.categories.includes(category);
  return {
    conversations: included
      ? [
          {
            id: reviewedConversationId,
            customer_reference: "Customer ••••4242",
            control_state: "AI_ACTIVE",
            message_count: conversationMessages.length,
            opened_at: now,
            latest_message_at: now,
            review: conversationReviewState,
          },
        ]
      : [],
    eval_drafts: evalCaseDrafts,
    categories: conversationCategories,
    labels: conversationLabels,
  };
}

function simulatedTestRun(tenantId, body) {
  return {
    id: "63000000-0000-4000-8000-000000000001",
    tenant_id: tenantId,
    mode: body.mode,
    simulated: true,
    response:
      "Simulated response: the cancellation request was recorded without calling Production.",
    agent_spec: { id: "agent-test", digest: "9".repeat(64), state: "DRAFT" },
    knowledge: { id: "knowledge-test", digest: "b".repeat(64), state: "TEST" },
    intent: "request_order_cancellation",
    capability: "orders",
    identity: { required_level: 2, status: "SIMULATED_VERIFIED" },
    tools: [
      {
        name: "orders.request_order_cancellation",
        status: "SIMULATED",
        arguments: { fixture: "sandbox" },
        result: { ok: true, external_effect: false },
      },
    ],
    sources: [
      { knowledge_version_id: "knowledge-test", authority: "TEST_FIXTURE" },
    ],
    action: {
      name: "orders.request_order_cancellation",
      status: "SIMULATED",
      external_effect: false,
    },
    approval: { required: true, status: "SIMULATED" },
    usage: {
      model_tokens: 24,
      messages: 2,
      external_requests: 0,
      tool_calls: 1,
      cost: { amount: "0.000000", currency: "USD", kind: "SIMULATED" },
    },
    latency_ms: 1,
    trace_id: "64000000-0000-4000-8000-000000000001",
    created_at: now,
  };
}

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

const operationalCaseId = "70000000-0000-4000-8000-000000000043";
const operationalCase = {
  id: operationalCaseId,
  capability: "returns_claims",
  issue_type: "damaged_product",
  revision: 3,
  status: "IN_PROGRESS",
  priority: "CRITICAL",
  target_status: "OVERDUE",
  target_at: "2026-08-31T14:00:00Z",
  reviewer_reference: "Platform admin ••••0043",
  approval_status: "APPROVED",
  latest_event: "STATE_CHANGED",
  latest_reason: "Approval received for human review.",
  updated_at: now,
};
const deadLetters = ["RETRY", "DISCARD", "RESOLVE"].map((action, index) => ({
  id: `71000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  outbox_job_id: `72000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  topic: `orders.${action.toLowerCase()}_fixture`,
  reason_code: "provider_timeout",
  status: "open",
  attempt_count: 5,
  max_attempts: 5,
  last_error_code: "provider_timeout",
  created_at: now,
  updated_at: now,
}));
const operationalAudits = [];
let qualityGateDecision = null;

function operationsWorkspace() {
  const openDeadLetters = deadLetters.filter((item) => item.status === "open");
  return {
    generated_at: now,
    state:
      openDeadLetters.length > 0 ||
      integrationConnections.some((item) =>
        ["ERROR", "REAUTH_REQUIRED"].includes(item.health.status),
      )
        ? "DEGRADED"
        : "IDLE",
    topics: [
      {
        topic: "orders.worker",
        pending: 2,
        processing: 0,
        failed: openDeadLetters.length > 0 ? 1 : 0,
        dead_letter: openDeadLetters.length,
        oldest_pending_at: "2026-09-01T14:40:00Z",
        state: openDeadLetters.length > 0 ? "DEGRADED" : "ACTIVE",
        state_basis: "RECORDED_QUEUE_STATE",
      },
    ],
    integrations: integrationConnections
      .filter((item) => item.status !== "REVOKED")
      .map((item) => ({
        id: item.id,
        connector_name: item.connector_name,
        connection_status: item.status,
        health_status: item.health.status,
        last_health_checked_at: item.health.checked_at,
        last_error_code: item.health.error_code,
      })),
    dead_letters: deadLetters,
    dead_letter_page: 1,
    dead_letter_has_more: false,
    recent_audit: operationalAudits,
    health: {
      generated_at: now,
      state: "DEGRADED",
      components: [
        {
          component: "google_calendar",
          state: "DEGRADED",
          observed_at: now,
          reason_code: "reauth_required",
        },
      ],
    },
    incidents: [
      {
        id: "76000000-0000-4000-8000-000000000001",
        incident_type: "connector_reauth_required",
        severity: "WARNING",
        status: "OPEN",
        title: "Google Calendar requires reconnection",
        correlation_id: "76000000-0000-4000-8000-000000000002",
        occurrence_count: 1,
        first_detected_at: now,
        last_detected_at: now,
        evidence_until: "2026-09-02T16:00:00Z",
      },
    ],
    quality_gate: {
      available: true,
      exact_version_required: true,
      latest: qualityGateDecision,
    },
    deployments: {
      available: true,
      promotion_mode: "GITHUB_ENVIRONMENT_APPROVAL",
      latest: [],
    },
  };
}

function usageSummary(dimension) {
  const groups = {
    tenant: [tenants[0].id],
    conversation: [reviewedConversationId],
    case: [operationalCaseId],
    action: ["73000000-0000-4000-8000-000000000043"],
  };
  const group = (groups[dimension] ?? groups.tenant)[0];
  return {
    dimension: groups[dimension] ? dimension : "tenant",
    groups: [
      {
        group,
        currency: "USD",
        records: 12,
        known_cost: "12.340000000000",
        unknown_cost_records: 0,
        input_tokens: "1200",
        cached_input_tokens: "300",
        output_tokens: "240",
        reasoning_tokens: "20",
        requests: "8",
        average_latency_ms: "410.5",
        complete_cost: true,
      },
    ],
    has_more: false,
    recorded_data_only: true,
  };
}

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
  ["test", "Test", "/test-console"],
  ["quality-gate", "Quality Gate", "/agent"],
  ["production", "Production", "/agent"],
];

function onboardingStatus(tenantId) {
  const steps = onboardingSteps.map(([slug, name, suffix], index) => {
    let status = index < 10 ? "COMPLETE" : "BLOCKED";
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
      status = onboardingConfigurationChanged
        ? "BLOCKED"
        : qualityGateDecision?.passed
          ? "COMPLETE"
          : "READY";
      blockers = onboardingConfigurationChanged
        ? [
            {
              code: "test_required",
              message: "Complete the current Test candidate first.",
            },
          ]
        : qualityGateDecision?.passed
          ? []
          : [
              {
                code: "production_quality_gate_required",
                message:
                  "Run a passing Production Quality Gate for the exact candidate digests.",
              },
            ];
    }
    if (slug === "production") {
      status =
        qualityGateDecision?.passed && !onboardingConfigurationChanged
          ? "READY"
          : "BLOCKED";
      blockers = [
        qualityGateDecision?.passed && !onboardingConfigurationChanged
          ? {
              code: "production_publication_required",
              message: "Publish the approved exact candidate to Production.",
            }
          : {
              code: "quality_gate_required",
              message:
                "Production requires a passing exact-version Quality Gate.",
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
    complete_steps: steps.filter((step) => step.status === "COMPLETE").length,
    current_step_slug:
      steps.find((step) => step.status !== "COMPLETE")?.slug ?? "production",
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
  if (
    request.method === "POST" &&
    url.pathname === "/__test/integrations/reset"
  ) {
    const calendar = integrationConnections.find(
      (item) => item.connector_name === "google_calendar",
    );
    const sheets = integrationConnections.find(
      (item) => item.connector_name === "google_sheets",
    );
    Object.assign(calendar, {
      status: "REAUTH_REQUIRED",
      health: {
        status: "REAUTH_REQUIRED",
        checked_at: now,
        error_code: "oauth_expired",
      },
    });
    Object.assign(sheets, {
      status: "CONNECTED",
      health: { status: "HEALTHY", checked_at: now, error_code: null },
    });
    calendarHealthAttempts = 0;
    json(response, 204, null);
    return;
  }
  if (
    request.method === "GET" &&
    url.pathname === "/__test/production-call-count"
  ) {
    json(response, 200, { calls: productionConnectorCalls });
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

  const knowledgeWorkspaceMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/knowledge\/workspace$/,
  );
  if (knowledgeWorkspaceMatch && request.method === "GET") {
    json(response, 200, knowledgeWorkspace);
    return;
  }

  const knowledgeSourcesMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/knowledge\/sources$/,
  );
  if (knowledgeSourcesMatch && request.method === "POST") {
    const body = await readJson(request);
    knowledgeSequence += 1;
    const source = knowledgeSource(
      `50000000-0000-4000-8000-${String(knowledgeSequence).padStart(12, "0")}`,
      body.name,
      body.source_type,
      body.authority,
      body.configuration,
    );
    knowledgeWorkspace.sources.unshift({ source, latest_ingestion: null });
    json(response, 201, source);
    return;
  }

  const knowledgeUploadMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/knowledge\/sources\/([^/]+)\/uploads\/([^/]+)$/,
  );
  if (knowledgeUploadMatch && request.method === "PUT") {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    json(response, 201, {
      upload_key: decodeURIComponent(knowledgeUploadMatch[3]),
      size_bytes: Buffer.concat(chunks).length,
    });
    return;
  }

  const knowledgeIngestionMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/knowledge\/sources\/([^/]+)\/ingestions$/,
  );
  if (knowledgeIngestionMatch && request.method === "POST") {
    const sourceEntry = knowledgeWorkspace.sources.find(
      ({ source }) => source.id === knowledgeIngestionMatch[2],
    );
    if (!sourceEntry) {
      json(response, 404, { error: "not_found" });
      return;
    }
    knowledgeSequence += 1;
    sourceEntry.latest_ingestion = knowledgeIngestion(
      `51000000-0000-4000-8000-${String(knowledgeSequence).padStart(12, "0")}`,
      sourceEntry.source.id,
    );
    const testVersion = knowledgeWorkspace.versions.find(
      ({ version: item }) => item.state === "TEST",
    );
    if (testVersion && sourceEntry.source.source_type === "WEBSITE") {
      const nextNumber =
        Math.max(
          ...knowledgeWorkspace.versions.map(({ version: item }) =>
            Number(item.version_number),
          ),
        ) + 1;
      const nextDraft = knowledgeVersion(
        nextNumber,
        "DRAFT",
        null,
        "f".repeat(64),
      );
      knowledgeWorkspace.versions.unshift(nextDraft);
      const proposalId = `52000000-0000-4000-8000-${String(knowledgeSequence).padStart(12, "0")}`;
      knowledgeWorkspace.proposals.unshift(
        knowledgeProposal(proposalId, sourceEntry.source.id, "DOCUMENT", {
          source_id: sourceEntry.source.id,
          authority: sourceEntry.source.authority,
          category: "DOCUMENTATION",
          title: "Connected source update",
          text: "A synchronized source changed after the Test promotion.",
          locator: { path: "/business", section: "updated" },
          content_digest: "f".repeat(64),
        }),
      );
      knowledgeWorkspace.diffs.unshift({
        id: proposalId.replace("5200", "5400"),
        source_id: sourceEntry.source.id,
        ingestion_id: sourceEntry.latest_ingestion.id,
        draft_version_id: nextDraft.version.id,
        previous_digest: "b".repeat(64),
        current_digest: "f".repeat(64),
        state: "DETECTED",
        summary: {
          message:
            "The connected source changed; Production remains immutable.",
        },
        created_at: now,
      });
    }
    json(response, 202, sourceEntry.latest_ingestion);
    return;
  }

  const knowledgeProposalMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/knowledge\/proposals\/([^/]+)\/review$/,
  );
  if (knowledgeProposalMatch && request.method === "POST") {
    const body = await readJson(request);
    const proposal = knowledgeWorkspace.proposals.find(
      (item) => item.id === knowledgeProposalMatch[2],
    );
    if (!proposal || proposal.state !== "PROPOSED") {
      problem(
        response,
        409,
        "knowledge_proposal_stale",
        "Reload before reviewing.",
      );
      return;
    }
    proposal.state =
      body.decision === "EDIT"
        ? "EDITED"
        : body.decision === "APPROVE"
          ? "APPROVED"
          : "REJECTED";
    proposal.decision_payload = body.edited_payload ?? null;
    proposal.decided_by_admin_id = "10000000-0000-4000-8000-000000000001";
    const conflict = knowledgeWorkspace.conflicts.find(
      (item) => item.proposal_id === proposal.id,
    );
    if (conflict) {
      conflict.state = "RESOLVED";
      conflict.resolution = proposal.state;
    }
    json(response, 200, proposal);
    return;
  }

  const knowledgeEmbeddingsMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/knowledge\/versions\/([^/]+)\/embeddings$/,
  );
  if (knowledgeEmbeddingsMatch && request.method === "POST") {
    knowledgeEmbeddingsReady = true;
    json(response, 202, {
      job_id: "56000000-0000-4000-8000-000000000001",
      knowledge_version_id: knowledgeEmbeddingsMatch[2],
    });
    return;
  }

  const knowledgeTestMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/knowledge\/versions\/([^/]+)\/test-v0$/,
  );
  if (knowledgeTestMatch && request.method === "POST") {
    const overview = knowledgeWorkspace.versions.find(
      ({ version: item }) => item.id === knowledgeTestMatch[2],
    );
    if (
      !overview ||
      !knowledgeEmbeddingsReady ||
      knowledgeWorkspace.proposals.some((item) => item.state === "PROPOSED") ||
      knowledgeWorkspace.conflicts.some((item) => item.state === "OPEN")
    ) {
      problem(
        response,
        409,
        "knowledge_test_readiness_required",
        "Complete reviews and semantic indexing first.",
      );
      return;
    }
    overview.version.state = "TEST";
    overview.version.digest = overview.candidate_digest;
    overview.v0_evaluation = "PASSED";
    overview.v0_passed_cases = 3;
    json(response, 200, overview.version);
    return;
  }

  const knowledgeProductionMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/knowledge\/versions\/([^/]+)\/production$/,
  );
  if (knowledgeProductionMatch && request.method === "POST") {
    problem(
      response,
      409,
      "production_quality_gate_required",
      "Production requires the full Task 45 Quality Gate for the exact Knowledge digest.",
    );
    return;
  }

  const conversationWorkspaceMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/conversations\/review-workspace$/,
  );
  if (conversationWorkspaceMatch && request.method === "GET") {
    json(
      response,
      200,
      conversationWorkspace(url.searchParams.get("category")),
    );
    return;
  }

  const conversationDetailMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/conversations\/([^/]+)\/review-detail$/,
  );
  if (conversationDetailMatch && request.method === "GET") {
    if (conversationDetailMatch[2] !== reviewedConversationId) {
      json(response, 404, { error: "not_found" });
      return;
    }
    json(response, 200, {
      conversation: conversationWorkspace(null).conversations[0],
      messages: conversationMessages,
    });
    return;
  }

  const conversationReviewMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/conversations\/([^/]+)\/review$/,
  );
  if (conversationReviewMatch && request.method === "PUT") {
    const body = await readJson(request);
    if (body.expected_revision !== conversationReviewState.revision) {
      problem(
        response,
        409,
        "conversation_review_stale",
        "Reload before saving.",
      );
      return;
    }
    conversationReviewState.revision += 1;
    conversationReviewState.categories = body.categories;
    conversationReviewState.labels = body.labels;
    conversationReviewState.note = body.note;
    json(response, 200, conversationReviewState);
    return;
  }

  const evalDraftMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/conversations\/([^/]+)\/eval-drafts$/,
  );
  if (evalDraftMatch && request.method === "POST") {
    await readJson(request);
    const id = `65000000-0000-4000-8000-${String(evalCaseDrafts.length + 1).padStart(12, "0")}`;
    const toolName = "orders.request_order_cancellation";
    const draft = {
      id,
      conversation_id: evalDraftMatch[2],
      case_id: `review-${id.replaceAll("-", "").slice(0, 20)}`,
      schema_version: 1,
      payload: {
        schema_version: 1,
        case_id: `review-${id.replaceAll("-", "").slice(0, 20)}`,
        input_turn: {
          message: "Cancel order 1042 and email me at [email].",
          active_capabilities: ["orders"],
          permitted_tools: [toolName],
          relevant_capabilities: ["orders"],
        },
        fixture_setup: {
          fake_outputs: [conversationMessages[1].text],
          tools: [
            {
              name: toolName,
              capability: "orders",
              description: "Sanitized conversation review fixture.",
              input_schema: { type: "object", properties: {} },
              active: true,
            },
          ],
        },
        expected: {
          response_required: true,
          selected_tools: [toolName],
          persisted_result: true,
          credentials_absent: true,
        },
        graders: [
          "response_exists",
          "selected_tools",
          "persisted_result",
          "credentials_absent",
        ],
        tags: ["conversation-review", "incorrect"],
      },
      status: "DRAFT",
      created_at: now,
    };
    evalCaseDrafts.unshift(draft);
    json(response, 201, draft);
    return;
  }

  const testReadinessMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/test-console\/readiness$/,
  );
  if (testReadinessMatch && request.method === "GET") {
    json(response, 200, {
      sandbox_available: true,
      real_test_available: false,
      real_test_reason:
        "A dedicated test tenant and provider accounts have not been configured.",
    });
    return;
  }

  const testRunMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/test-console\/runs$/,
  );
  if (testRunMatch && request.method === "POST") {
    const body = await readJson(request);
    if (body.mode === "REAL_TEST_ENVIRONMENT") {
      problem(
        response,
        409,
        "real_test_environment_required",
        "Dedicated test accounts are required.",
      );
      return;
    }
    json(response, 200, simulatedTestRun(testRunMatch[1], body));
    return;
  }

  const caseWorkspaceMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/case-workspace$/,
  );
  if (caseWorkspaceMatch && request.method === "GET") {
    const priority = url.searchParams.get("priority");
    const overdue = url.searchParams.get("overdue") === "true";
    const page = Number(url.searchParams.get("page") ?? "1");
    const included =
      (!priority || operationalCase.priority === priority) &&
      (!overdue ||
        (operationalCase.target_status === "OVERDUE" &&
          operationalCase.status !== "RESOLVED"));
    json(response, 200, {
      generated_at: now,
      cases: included ? [operationalCase] : [],
      page,
      limit: 25,
      total: included ? 1 : 0,
      has_more: false,
    });
    return;
  }

  const resolveCaseMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/cases\/([^/]+)\/resolve$/,
  );
  if (resolveCaseMatch && request.method === "POST") {
    const body = await readJson(request);
    if (
      resolveCaseMatch[2] !== operationalCase.id ||
      operationalCase.status !== "IN_PROGRESS" ||
      body.expected_revision !== operationalCase.revision
    ) {
      problem(
        response,
        409,
        "case_changed_requires_review",
        "Reload the case.",
      );
      return;
    }
    operationalCase.status = "RESOLVED";
    operationalCase.target_status = "OVERDUE";
    operationalCase.revision += 1;
    operationalCase.latest_event = "STATE_CHANGED";
    operationalCase.latest_reason = body.reason;
    operationalCase.updated_at = now;
    json(response, 200, {
      ...operationalCase,
      tenant_id: resolveCaseMatch[1],
      customer_ref: "masked-by-operational-route",
      binding_id: "74000000-0000-4000-8000-000000000043",
      resource_id: "order-43",
      deduplication_key: "a".repeat(64),
      content_digest: "b".repeat(64),
      intake: {},
      policy: {
        close_after_hours: 72,
        target_minutes: { LOW: 2880, NORMAL: 1440, HIGH: 240, CRITICAL: 30 },
        approaching_fraction: 0.8,
        priority_by_issue: {},
      },
      approaching_at: "2026-08-31T13:30:00Z",
      resolved_at: now,
      close_at: "2026-09-04T15:00:00Z",
      customer_result: body.customer_result,
      result_recorded_by: "10000000-0000-4000-8000-000000000043",
      created_at: "2026-08-31T13:00:00Z",
    });
    return;
  }

  const usageSummaryMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/usage\/summary$/,
  );
  if (usageSummaryMatch && request.method === "GET") {
    json(
      response,
      200,
      usageSummary(url.searchParams.get("dimension") ?? "tenant"),
    );
    return;
  }

  const usageFreshnessMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/usage\/freshness$/,
  );
  if (usageFreshnessMatch && request.method === "GET") {
    json(response, 200, {
      generated_at: now,
      latest_recorded_at: "2026-09-01T14:58:00Z",
      records: 128,
      state: "fresh",
    });
    return;
  }

  const usageMarginMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/usage\/margin$/,
  );
  if (usageMarginMatch && request.method === "GET") {
    const revenue = Number(url.searchParams.get("revenue_amount"));
    const variableCost = 12.34;
    json(response, 200, {
      currency: url.searchParams.get("currency") ?? "USD",
      revenue: revenue.toFixed(12),
      variable_cost: variableCost.toFixed(12),
      gross_profit: (revenue - variableCost).toFixed(12),
      gross_margin_percent: (
        ((revenue - variableCost) * 100) /
        revenue
      ).toFixed(12),
      reason: null,
    });
    return;
  }

  const operationsWorkspaceMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/operations\/workspace$/,
  );
  if (operationsWorkspaceMatch && request.method === "GET") {
    json(response, 200, operationsWorkspace());
    return;
  }

  const deadLetterActionMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/operations\/dead-letters\/([^/]+)\/actions$/,
  );
  if (deadLetterActionMatch && request.method === "POST") {
    const body = await readJson(request);
    const item = deadLetters.find(
      (entry) => entry.id === deadLetterActionMatch[2],
    );
    if (!item || item.status !== "open" || body.confirmation !== true) {
      problem(response, 409, "dead_letter_changed", "Reload the work item.");
      return;
    }
    item.status = body.action === "DISCARD" ? "discarded" : "resolved";
    item.updated_at = now;
    operationalAudits.unshift({
      event_type: `job.dead_letter.${body.action.toLowerCase()}`,
      entity_id: item.id,
      correlation_id: `75000000-0000-4000-8000-${String(operationalAudits.length + 1).padStart(12, "0")}`,
      occurred_at: now,
    });
    json(response, 200, item);
    return;
  }

  const qualityGateMutationMatch = url.pathname.match(
    /^\/admin\/tenants\/([^/]+)\/evals\/quality-gate\/runs$/,
  );
  if (qualityGateMutationMatch && request.method === "POST") {
    const body = await readJson(request);
    qualityGateDecision = {
      id: "77000000-0000-4000-8000-000000000001",
      eval_run_id: "77000000-0000-4000-8000-000000000002",
      passed: true,
      agent_spec_digest: body.agent_spec_digest,
      knowledge_digest: body.knowledge_digest,
      code_digest: body.code_digest,
      hard_blockers: [],
      passed_cases: 79,
      failed_cases: 0,
      runner_version: "production-v1",
      decided_at: now,
    };
    json(response, 200, qualityGateDecision);
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
