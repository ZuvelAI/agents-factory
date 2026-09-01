import { createServer } from "node:http";

const port = Number(process.env.FAKE_DASHBOARD_PORT ?? "8000");

function json(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(body));
}

createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  if (request.method === "GET" && url.pathname === "/admin/dashboard") {
    if (!request.headers.authorization?.startsWith("Bearer ")) {
      json(response, 401, { error: "authentication_required" });
      return;
    }
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

  json(response, 404, { error: "not_found" });
}).listen(port, "127.0.0.1");
