// Synthetic browser contract fixture, never worker/database evidence.
let states = new Map(),
  mode = "normal",
  attempts = 0;
export function fixtureOperation(tenant, agent) {
  const key = `${tenant}:${agent}`;
  if (!states.has(key))
    states.set(key, {
      tenant_id: tenant,
      agent_instance_id: agent,
      enabled: true,
      revision: 1,
      resumed_at: null,
      updated_at: "2026-10-21T12:00:00Z",
      controls_available: true,
    });
  return { ...states.get(key), controls_available: mode !== "disabled" };
}
export async function handleAgentOperations(
  request,
  response,
  url,
  json,
  readJson,
) {
  if (url.pathname === "/__agent-operation/reset") {
    states = new Map();
    mode = "normal";
    attempts = 0;
    json(response, 200, {});
    return true;
  }
  if (url.pathname === "/__agent-operation/mode") {
    mode = (await readJson(request)).mode;
    json(response, 200, {});
    return true;
  }
  if (url.pathname === "/__agent-operation/stats") {
    json(response, 200, { attempts });
    return true;
  }
  const match = url.pathname.match(
    /^\/admin\/agent-workspace\/companies\/([^/]+)\/agents\/([^/]+)\/operation$/,
  );
  if (!match) return false;
  const current = fixtureOperation(match[1], match[2]);
  if (request.method === "GET") {
    json(response, 200, current);
    return true;
  }
  const body = await readJson(request);
  attempts++;
  if (mode === "slow")
    await new Promise((resolve) => setTimeout(resolve, 1200));
  const fail = (status) =>
    json(response, status, {
      type: "https://example.test/problem",
      title: "Operation unavailable",
      status,
      code:
        status === 409
          ? "agent_operation_revision_conflict"
          : "operation_unavailable",
      detail: "SYNTHETIC_PRIVATE_DIAGNOSTIC",
      correlation_id: match[2],
    });
  if (mode === "error" || mode === "disabled") {
    fail(503);
    return true;
  }
  if (mode === "conflict") {
    states.set(`${match[1]}:${match[2]}`, {
      ...current,
      enabled: false,
      revision: current.revision + 1,
    });
    mode = "normal";
    fail(409);
    return true;
  }
  if (body.expected_revision !== current.revision) {
    fail(409);
    return true;
  }
  if (body.enabled !== current.enabled) {
    current.enabled = body.enabled;
    current.revision++;
    current.updated_at = new Date().toISOString();
    if (body.enabled) current.resumed_at = current.updated_at;
  }
  states.set(`${match[1]}:${match[2]}`, current);
  json(response, 200, current);
  return true;
}
