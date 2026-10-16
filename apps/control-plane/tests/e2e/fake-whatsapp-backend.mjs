import { createServer } from "node:http";
import { handleAgentPublication } from "./fake-agent-publication.mjs";
import { handleAgentWorkspace } from "./fake-agent-workspace.mjs";
import { handleAgentConfiguration } from "./fake-agent-configuration.mjs";

const port = Number(process.env.FAKE_WHATSAPP_BACKEND_PORT ?? "3132");
const tenantId = "019c2000-0000-7000-8000-000000000102";
const accountId = "019c2000-0000-7000-8000-000000000202";
const conversationId = "019c2000-0000-7000-8000-000000000303";
const alertId = "019c2000-0000-7000-8000-000000000777";
const adminId = "019c2000-0000-7000-8000-000000000111";
const accountPath = `/admin/tenants/${tenantId}/whatsapp`;
const stalledAvailabilityPath =
  "/admin/tenants/019c2000-0000-7000-8000-000000000103/whatsapp";
const alertsPath = "/admin/whatsapp/account-update-alerts";
let resumed = false;
let resolution = null;

function json(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(body));
}

function isAdminRequest(request) {
  const authorization = request.headers.authorization;
  if (!authorization?.startsWith("Bearer ")) return false;
  try {
    const payload = JSON.parse(
      Buffer.from(authorization.slice(7).split(".")[1], "base64url").toString(),
    );
    return payload.app_metadata?.platform_role === "platform_admin";
  } catch {
    return false;
  }
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

createServer(async (request, response) => {
  if (!isAdminRequest(request)) {
    json(response, 401, { error: "unauthorized" });
    return;
  }
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  if (await handleAgentConfiguration(request, response, url, json, readJson)) return;
  if (handleAgentWorkspace(request, response, url, json)) return;
  if (url.pathname === `${stalledAvailabilityPath}/signup/availability`) {
    // The account endpoints work, but this optional request never resolves.
    return;
  }
  const pathname = url.pathname.replace(stalledAvailabilityPath, accountPath);
  if (await handleAgentPublication(request, response, pathname, readJson, json))
    return;
  if (
    request.method === "GET" &&
    pathname === `${accountPath}/signup/availability`
  ) {
    json(response, 200, { coexistence_enabled: true });
    return;
  }
  if (request.method === "GET" && pathname === `${alertsPath}/summary`) {
    json(response, 200, { open_count: resolution ? 0 : 1 });
    return;
  }
  if (request.method === "GET" && pathname === alertsPath) {
    const status = url.searchParams.get("status");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    const include =
      offset === 0 &&
      (status === null ||
        (status === "open" && !resolution) ||
        (status === "resolved" && resolution));
    json(
      response,
      200,
      include
        ? [
            {
              id: alertId,
              waba_id: "waba-ambiguous",
              event: "ACCOUNT_OFFBOARDED",
              display_phone_digits: "15550123456",
              occurred_at: "2026-09-28T10:00:00Z",
              reason: "unmatched",
              received_at: "2026-09-28T10:01:00Z",
              resolved_at: resolution?.resolved_at ?? null,
              resolved_by: resolution?.resolved_by ?? null,
              resolution_note: resolution?.resolution_note ?? null,
            },
          ]
        : [],
    );
    return;
  }
  if (
    request.method === "POST" &&
    pathname === `${alertsPath}/${alertId}/resolve`
  ) {
    const body = await readJson(request);
    if (resolution) {
      json(response, 409, { error: "already_resolved" });
      return;
    }
    if (typeof body.note !== "string" || !body.note.trim()) {
      json(response, 422, { error: "invalid_note" });
      return;
    }
    resolution = {
      alert_id: alertId,
      resolved_by: adminId,
      resolution_note: body.note.trim(),
      resolved_at: "2026-09-28T11:00:00Z",
    };
    json(response, 200, resolution);
    return;
  }
  if (request.method === "GET" && pathname === accountPath) {
    json(response, 200, [
      {
        id: accountId,
        business_id: "business-123",
        waba_id: "waba-123",
        phone_number_id: "phone-123",
        display_phone_digits: "15550783881",
        status: "active",
        mode: "COEXISTENCE",
        coexistence_eligibility: "ELIGIBLE",
        granted_scopes: [
          "whatsapp_business_management",
          "whatsapp_business_messaging",
        ],
        health_status: "HEALTHY",
        last_health_checked_at: null,
        token_expires_at: null,
        verified_at: "2026-09-27T00:00:00Z",
      },
    ]);
    return;
  }
  if (
    request.method === "GET" &&
    pathname === `${accountPath}/${accountId}/human-active-conversations`
  ) {
    json(
      response,
      200,
      resumed
        ? []
        : [
            {
              conversation_id: conversationId,
              customer_hint: "***0002",
              state_version: 3,
            },
          ],
    );
    return;
  }
  if (
    request.method === "GET" &&
    pathname === `${accountPath}/${accountId}/sync-status`
  ) {
    json(response, 200, [
      {
        sync_type: "smb_app_state_sync",
        state: "ACCEPTED",
        request_id: "contacts-request",
        reserved_at: "2026-09-27T00:00:00Z",
      },
      {
        sync_type: "history",
        state: "NOT_REQUESTED",
        request_id: null,
        reserved_at: null,
      },
    ]);
    return;
  }
  if (
    request.method === "GET" &&
    pathname === `${accountPath}/${accountId}/sync-observations`
  ) {
    json(response, 200, {
      active_contacts: 2,
      history_batches_received: 0,
      history_batches_imported: 0,
      history_batches_declined: 0,
      history_batches_pending: 0,
    });
    return;
  }
  if (
    request.method === "POST" &&
    pathname ===
      `${accountPath}/${accountId}/conversations/${conversationId}/resume-ai`
  ) {
    const body = await readJson(request);
    if (resumed || body.expected_version !== 3) {
      json(response, 409, { error: "stale_state" });
      return;
    }
    resumed = true;
    json(response, 200, {
      conversation_id: conversationId,
      control_state: "AI_ACTIVE",
      state_version: 4,
    });
    return;
  }
  json(response, 404, { error: "not_found" });
}).listen(port, "127.0.0.1");
