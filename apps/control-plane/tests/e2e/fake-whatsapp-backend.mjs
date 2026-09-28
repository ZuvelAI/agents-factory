import { createServer } from "node:http";

const port = Number(process.env.FAKE_WHATSAPP_BACKEND_PORT ?? "3132");
const tenantId = "019c2000-0000-7000-8000-000000000102";
const accountId = "019c2000-0000-7000-8000-000000000202";
const conversationId = "019c2000-0000-7000-8000-000000000303";
const accountPath = `/admin/tenants/${tenantId}/whatsapp`;
let resumed = false;

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
  const pathname = new URL(request.url ?? "/", `http://127.0.0.1:${port}`)
    .pathname;
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
