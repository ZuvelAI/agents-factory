// Test-only loopback backend. Never imported by production code.
import { createServer } from "node:http";

const closed = new Set();
let decisions = 0;
const challenge = "10000000-0000-4000-8000-000000000001";
const allowed = "reviewer@example.test";
createServer(async (request, response) => {
  response.setHeader("Content-Type", "application/json");
  response.setHeader("Cache-Control", "no-store");
  if (request.url === "/fixture/stats")
    return response.end(JSON.stringify({ decisions }));
  let raw = "";
  for await (const chunk of request) raw += chunk;
  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    response.statusCode = 400;
    return response.end("{}");
  }
  const link = typeof input.link_token === "string" ? input.link_token : "";
  if (
    link.includes("eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee") ||
    !link.startsWith("a1.") ||
    closed.has(link)
  )
    return response.end(
      JSON.stringify({ status: "CLOSED", result: null, details: null }),
    );
  if (link.includes("ffffffffffffffffffffffffffffffff")) {
    response.statusCode = 429;
    return response.end(
      JSON.stringify({ detail: "private_provider_diagnostic" }),
    );
  }
  if (request.url === "/approvals/inspect")
    return response.end(JSON.stringify({ status: "OPEN" }));
  if (request.url === "/approvals/otp")
    return response.end(
      JSON.stringify({ status: "IF_AUTHORIZED_SENT", challenge_id: challenge }),
    );
  if (
    input.email !== allowed ||
    input.code !== "123456" ||
    input.challenge_id !== challenge
  )
    return response.end(JSON.stringify({ status: "INVALID_VERIFICATION" }));
  if (request.url === "/approvals/review")
    return response.end(
      JSON.stringify({
        status: "OPEN",
        details: {
          request_id: "20000000-0000-4000-8000-000000000001",
          action: "orders.request_order_cancellation",
          resource_reference: "42",
          expires_at: new Date(Date.now() + 600000).toISOString(),
          private_customer_email: "hidden@example.test",
        },
      }),
    );
  if (request.url === "/approvals/decision") {
    if (!input.requested_result?.explanation) {
      response.statusCode = 422;
      return response.end("{}");
    }
    closed.add(link);
    decisions += 1;
    const approved = input.decision === "APPROVE";
    return response.end(
      JSON.stringify({
        status: "RECORDED",
        result: {
          status: approved ? "pending_execution" : "rejected",
          reason_code: approved ? "approval_recorded" : "reviewer_rejected",
          customer_safe_explanation: "untrusted raw connector output",
          next_actions: ["refund_money"],
        },
      }),
    );
  }
  response.statusCode = 404;
  response.end("{}");
}).listen(8132, "127.0.0.1");
