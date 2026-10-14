// Synthetic UI contract fixture; real persistence/authorization is tested in backend integration tests.
const tenant = "019c2000-0000-7000-8000-000000000102";
const account = "019c2000-0000-7000-8000-000000000202";
const versionId = "019c2000-0000-7000-8000-000000000901";
const runId = "019c2000-0000-7000-8000-000000000902";
const root = `/admin/tenants/${tenant}`;
const publication = `${root}/agent-publication`;
let revision = 1;
let agent = {
  greeting: "Bienvenido a Zuvel",
  instructions: "Orienta sobre servicios",
  supported_languages: ["es-CO"],
  tone: "PROFESSIONAL_WARM",
  formality: "USTED",
  greeting_style: "BRAND_ONLY",
};
let candidate = null,
  run = null,
  binding = null;
const keys = [
  "company",
  "agent",
  "capabilities",
  "integrations",
  "knowledge",
  "policies-identity",
  "human-operations",
  "approval-routes",
  "whatsapp",
  "test",
  "quality-gate",
  "production",
];
function wizard() {
  const steps = keys.map((key, index) => ({
    key,
    position: index + 1,
    title: key,
    instructions: "Configura y revisa este paso.",
    status: index < 9 ? "COMPLETE" : binding ? "COMPLETE" : "BLOCKED",
    required_fields: [],
    test_actions: [],
    blockers: [],
    warnings: [],
    documentation_links: [],
    data: key === "agent" ? agent : {},
  }));
  return {
    tenant_id: tenant,
    tenant_name: "Zuvel",
    revision,
    updated_at: "2026-10-13T00:00:00Z",
    current_step: "agent",
    completed_steps: binding ? 12 : 9,
    total_steps: 12,
    steps,
  };
}
export async function handleAgentPublication(
  request,
  response,
  path,
  readJson,
  json,
) {
  if (path === "/admin/tenants" && request.method === "GET") {
    json(response, 200, [
      { id: tenant, slug: "zuvel", name: "Zuvel", status: "active" },
    ]);
    return true;
  }
  if (path === `${root}/onboarding` && request.method === "GET") {
    json(response, 200, wizard());
    return true;
  }
  if (path === `${root}/onboarding/agent` && request.method === "PATCH") {
    const body = await readJson(request);
    if (body.expected_revision !== revision) {
      json(response, 409, { error: "stale" });
      return true;
    }
    agent = body.data;
    revision++;
    json(response, 200, wizard());
    return true;
  }
  if (!path.startsWith(publication)) return false;
  if (path === publication && request.method === "GET") {
    json(response, 200, {
      saved_revision: revision,
      candidates: candidate ? [candidate] : [],
      accounts: [
        {
          id: account,
          display_phone_number: "15550783881",
          status: "active",
          health_status: "HEALTHY",
        },
      ],
      bindings: binding ? [binding] : [],
      blockers: [],
    });
    return true;
  }
  if (path === `${publication}/candidates` && request.method === "POST") {
    const body = await readJson(request);
    if (body.expected_revision !== revision) {
      json(response, 409, { error: "stale" });
      return true;
    }
    candidate = {
      id: versionId,
      version_number: 1,
      state: "TEST",
      greeting: agent.greeting,
    };
    json(response, 200, candidate);
    return true;
  }
  if (
    path === `${publication}/candidates/${versionId}/tests` &&
    request.method === "POST"
  ) {
    run = {
      id: runId,
      version_id: versionId,
      onboarding_revision: revision,
      is_current: true,
      approved: null,
      expires_at: "2099-01-01T00:00:00Z",
      result: {
        checks_passed: true,
        scenarios: [
          "greeting",
          "known_fact",
          "unknown_fact",
          "scope",
          "injection",
          "human_control",
        ].map((key) => ({
          key,
          prompt: key,
          response:
            key === "greeting"
              ? candidate.greeting
              : key === "human_control"
                ? null
                : "Respuesta sintética para revisión",
          passed: true,
          error_code: null,
        })),
      },
    };
    json(response, 202, run);
    return true;
  }
  if (path === `${publication}/tests/${runId}` && request.method === "GET") {
    json(response, 200, {
      ...run,
      is_current: run.onboarding_revision === revision,
    });
    return true;
  }
  if (
    path === `${publication}/tests/${runId}/review` &&
    request.method === "POST"
  ) {
    const body = await readJson(request);
    if (body.expected_revision !== revision) {
      json(response, 409, { error: "stale" });
      return true;
    }
    run.approved = body.approved;
    json(response, 200, run);
    return true;
  }
  if (path === `${publication}/publish` && request.method === "POST") {
    const body = await readJson(request);
    if (
      !run.approved ||
      body.expected_revision !== revision ||
      body.whatsapp_account_id !== account ||
      body.expected_binding_revision !== (binding?.revision ?? 0)
    ) {
      json(response, 409, { error: "invalid_publish" });
      return true;
    }
    binding = {
      tenant_id: tenant,
      whatsapp_account_id: account,
      agent_instance_id: versionId,
      version_id: versionId,
      revision: 1,
      updated_at: "2026-10-13T00:00:00Z",
    };
    candidate.state = "PRODUCTION";
    json(response, 200, binding);
    return true;
  }
  json(response, 404, { error: "fixture_not_found" });
  return true;
}
