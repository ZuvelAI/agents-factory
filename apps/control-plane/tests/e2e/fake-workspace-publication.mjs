// Synthetic HTTP UI fixture, not database/worker evidence.
import { randomUUID } from "node:crypto";
import { fixtureDraft } from "./fake-agent-configuration.mjs";
const accountId = "019c2000-0000-7000-8000-000000000202";
let candidates = new Map(),
  runs = new Map(),
  bindings = new Map(),
  hideCandidates = false,
  pageTwoOnly = false,
  hideSuites = false;
export async function handleWorkspacePublication(
  request,
  response,
  url,
  json,
  readJson,
) {
  if (url.pathname === "/__workspace-publication/reset") {
    candidates = new Map();
    runs = new Map();
    bindings = new Map();
    hideCandidates = false;
    pageTwoOnly = false;
    hideSuites = false;
    json(response, 200, {});
    return true;
  }
  if (url.pathname === "/__workspace-publication/page-two-only") {
    pageTwoOnly = true;
    json(response, 200, {});
    return true;
  }
  if (url.pathname === "/__workspace-publication/hide-suites") {
    hideSuites = true;
    json(response, 200, {});
    return true;
  }
  if (url.pathname === "/__workspace-publication/legacy-recovery") {
    const candidate = [...candidates.values()][0];
    const second = structuredClone(candidate);
    second.version.id = randomUUID();
    second.source.version_id = second.version.id;
    second.version.version_number = 2;
    second.version.state = "PRODUCTION";
    candidate.version.state = "PRODUCTION";
    candidates.set(second.version.id, second);
    bindings.set(accountId, {
      tenant_id: candidate.version.tenant_id,
      agent_instance_id: candidate.version.agent_instance_id,
      version_id: second.version.id,
      whatsapp_account_id: accountId,
      revision: 2,
    });
    hideCandidates = true;
    json(response, 200, {});
    return true;
  }
  const match = url.pathname.match(
    /^\/admin\/agent-workspace\/companies\/([^/]+)\/agents\/([^/]+)\/publication(.*)$/,
  );
  if (!match) return false;
  const [, tenant, agent, suffix] = match;
  const draft = fixtureDraft(agent);
  if (!draft || draft.tenant_id !== tenant) {
    json(response, 404, {});
    return true;
  }
  const failure = (code = "configuration_revision_conflict") =>
    json(response, 409, {
      type: "https://example.test/conflict",
      title: "Conflict",
      status: 409,
      code,
      detail: "Reload",
      correlation_id: agent,
    });
  const state = () => ({
    draft_revision: draft.revision,
    company_revision: draft.company_revision,
    blockers: draft.company_update_available
      ? ["Incorpora los cambios de empresa"]
      : [],
    candidates: [...candidates.values()]
      .filter(
        (c) =>
          !hideCandidates &&
          (!pageTwoOnly || url.searchParams.get("cursor") === "page-two") &&
          c.version.agent_instance_id === agent,
      )
      .reverse(),
    runs: [...runs.values()]
      .filter(
        (r) =>
          r.agent_instance_id === agent &&
          (!hideSuites || r.run_kind !== "SCENARIOS"),
      )
      .reverse()
      .map((r) => ({
        ...r,
        is_current:
          r.draft_revision === draft.revision &&
          !draft.company_update_available,
      })),
    accounts: [
      {
        id: accountId,
        display_phone_number: "+573124009568",
        status: "active",
        health_status: "HEALTHY",
        binding: bindings.get(accountId) ?? null,
        current_version:
          candidates.get(bindings.get(accountId)?.version_id)?.version ?? null,
      },
    ],
    versions: [...candidates.values()]
      .filter(
        (c) =>
          c.version.agent_instance_id === agent &&
          c.version.state === "PRODUCTION",
      )
      .map((c) => c.version),
    bindings: [...bindings.values()].filter(
      (b) => b.agent_instance_id === agent,
    ),
    rollback_targets: [...candidates.values()]
      .filter(
        (c) =>
          c.version.agent_instance_id === agent &&
          c.version.state === "PRODUCTION",
      )
      .map((c) => c.version.id),
    next_cursor: null,
    section: url.searchParams.get("section") ?? "candidates",
  });
  if (!suffix && request.method === "GET") {
    json(response, 200, state());
    return true;
  }
  if (request.method === "GET" && suffix.startsWith("/tests/")) {
    const run = runs.get(suffix.slice(7));
    if (!run || run.agent_instance_id !== agent) json(response, 404, {});
    else
      json(response, 200, {
        ...run,
        is_current:
          run.draft_revision === draft.revision &&
          !draft.company_update_available,
      });
    return true;
  }
  const body = await readJson(request);
  if (
    body.expected_revision !== undefined &&
    body.expected_revision !== draft.revision
  ) {
    failure();
    return true;
  }
  if (suffix === "/candidates") {
    let candidate = [...candidates.values()].find(
      (c) =>
        c.version.agent_instance_id === agent &&
        c.source.revision === draft.revision,
    );
    if (!candidate) {
      const id = randomUUID();
      candidate = {
        version: {
          id,
          tenant_id: tenant,
          agent_instance_id: agent,
          version_number:
            [...candidates.values()].filter(
              (c) => c.version.agent_instance_id === agent,
            ).length + 1,
          state: "TEST",
          compiled_digest: "a".repeat(64),
          configuration: {
            knowledge: { name: "Manual", version: "1", digest: "b".repeat(64) },
            approved_business_context: {
              summary: "Conocimiento congelado para comparar",
            },
            model: { model: draft.configuration.agent.model },
            persona: {
              instructions: draft.configuration.agent.instructions,
              business_name: draft.company_snapshot.commercial_name,
            },
          },
        },
        source: {
          source_kind: "AGENT_CONFIGURATION",
          version_id: id,
          agent_instance_id: agent,
          revision: draft.revision,
          company_revision: draft.company_revision,
          source_digest: "b".repeat(64),
          code_digest: "a".repeat(64),
        },
        created_at: "2026-10-16T12:00:00Z",
      };
      candidates.set(id, candidate);
    }
    json(response, 200, candidate);
    return true;
  }
  const test = suffix.match(/^\/candidates\/([^/]+)\/(tests|preview)$/);
  if (test) {
    const same = [...runs.values()].find(
      (r) => r.request_key === body.request_key,
    );
    if (same) {
      json(response, 202, same);
      return true;
    }
    if (body.messages?.at(-1)?.text === "conflicto-controlado") {
      failure();
      return true;
    }
    const candidate = candidates.get(test[1]);
    if (!candidate || candidate.version.agent_instance_id !== agent) {
      json(response, 404, {});
      return true;
    }
    const preview = test[2] === "preview",
      id = randomUUID();
    const run = {
      request_key: body.request_key,
      id,
      version_id: test[1],
      agent_instance_id: agent,
      source_kind: "AGENT_CONFIGURATION",
      draft_revision: draft.revision,
      run_kind: preview ? "PREVIEW" : "SCENARIOS",
      is_current: true,
      approved: null,
      expires_at: "2099-10-16T12:00:00Z",
      input_messages: preview ? body.messages : null,
      result: preview
        ? { response: "Respuesta simulada de Zuvel", error_code: null }
        : {
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
              prompt: "Pregunta de prueba",
              response: "Respuesta de escenario para revisión",
              passed: true,
              error_code: null,
            })),
          },
    };
    runs.set(id, run);
    if (body.messages?.at(-1)?.text === "respuesta-perdida") {
      json(response, 500, {});
      return true;
    }
    json(response, 202, run);
    return true;
  }
  const review = suffix.match(/^\/tests\/([^/]+)\/review$/);
  if (review) {
    const run = runs.get(review[1]);
    if (
      !run ||
      run.agent_instance_id !== agent ||
      run.run_kind !== "SCENARIOS"
    ) {
      json(response, 404, {});
      return true;
    }
    run.approved = body.approved;
    json(response, 200, run);
    return true;
  }
  if (suffix === "/publish") {
    const run = runs.get(body.test_run_id),
      candidate = candidates.get(body.version_id),
      current = bindings.get(accountId);
    if (
      !run?.approved ||
      !candidate ||
      candidate.source.revision !== draft.revision ||
      body.expected_binding_revision !== (current?.revision ?? 0) ||
      body.expected_current_agent_id !== (current?.agent_instance_id ?? null) ||
      !body.confirm_publish
    ) {
      failure();
      return true;
    }
    candidate.version.state = "PRODUCTION";
    const binding = {
      tenant_id: tenant,
      agent_instance_id: agent,
      whatsapp_account_id: accountId,
      version_id: body.version_id,
      revision: (current?.revision ?? 0) + 1,
    };
    bindings.set(accountId, binding);
    json(response, 200, binding);
    return true;
  }
  if (suffix === "/rollback") {
    const binding = bindings.get(accountId);
    if (
      !binding ||
      binding.revision !== body.expected_binding_revision ||
      !body.confirm_rollback
    ) {
      failure();
      return true;
    }
    binding.version_id = body.target_version_id;
    binding.revision++;
    json(response, 200, binding);
    return true;
  }
  json(response, 404, {});
  return true;
}
