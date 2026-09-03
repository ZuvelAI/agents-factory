"use server";

import { headers } from "next/headers";
import { approvalOrigin } from "../../../lib/approval-origin";
import {
  APPROVAL_REASONS,
  LINK_PATTERN,
  type ApprovalReply,
} from "../../../lib/approval-contract";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

export async function submitApproval(
  operation: string,
  input: unknown,
): Promise<ApprovalReply> {
  try {
    const origin = approvalOrigin();
    const incoming = await headers();
    if (
      !origin ||
      incoming.get("origin") !== origin.origin ||
      incoming.get("host") !== origin.host
    )
      return { status: "UNAVAILABLE" };
    if (!["inspect", "otp", "review", "decision"].includes(operation))
      return { status: "UNAVAILABLE" };
    const value = record(input);
    if (
      !value ||
      typeof value.link_token !== "string" ||
      !LINK_PATTERN.test(value.link_token)
    )
      return { status: "CLOSED" };
    const payload: Record<string, unknown> = { link_token: value.link_token };
    if (operation !== "inspect") {
      if (
        typeof value.email !== "string" ||
        value.email.length > 254 ||
        !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.email)
      )
        return { status: "INVALID_VERIFICATION" };
      payload.email = value.email.trim().toLowerCase();
    }
    if (operation === "review" || operation === "decision") {
      if (
        typeof value.code !== "string" ||
        !/^[0-9]{6}$/.test(value.code) ||
        typeof value.challenge_id !== "string" ||
        !uuid.test(value.challenge_id)
      )
        return { status: "INVALID_VERIFICATION" };
      payload.code = value.code;
      payload.challenge_id = value.challenge_id;
    }
    if (operation === "decision") {
      if (
        value.confirmed !== true ||
        !["APPROVE", "REJECT"].includes(String(value.decision)) ||
        typeof value.reason_code !== "string" ||
        !Object.hasOwn(APPROVAL_REASONS, value.reason_code) ||
        typeof value.explanation !== "string" ||
        !value.explanation.trim() ||
        value.explanation.length > 2000
      )
        return { status: "INVALID_VERIFICATION" };
      payload.decision = value.decision;
      payload.requested_result = {
        reason_code: value.reason_code,
        explanation: value.explanation.trim(),
        requested_next_actions: [],
      };
    }
    const base = new URL(process.env.BACKEND_API_URL ?? "");
    if (
      (base.protocol !== "https:" &&
        !(
          base.protocol === "http:" &&
          ["backend", "127.0.0.1", "localhost", "[::1]"].includes(base.hostname)
        )) ||
      base.username ||
      base.password ||
      base.search ||
      base.hash ||
      base.pathname !== "/"
    )
      return { status: "UNAVAILABLE" };
    const response = await fetch(new URL(`/approvals/${operation}`, base), {
      method: "POST",
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(20_000),
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Origin: origin.origin,
      },
      body: JSON.stringify(payload),
    });
    if (response.status === 429) return { status: "RATE_LIMITED" };
    if ([400, 403, 404, 409, 410].includes(response.status))
      return { status: "CLOSED" };
    if (!response.ok) return { status: "UNAVAILABLE" };
    const body = record(await response.json());
    if (!body) return { status: "UNAVAILABLE" };
    if (body.status === "CLOSED" || body.status === "INVALID_VERIFICATION")
      return { status: body.status };
    if (operation === "inspect" && body.status === "OPEN")
      return { status: "OPEN" };
    if (
      operation === "otp" &&
      body.status === "IF_AUTHORIZED_SENT" &&
      typeof body.challenge_id === "string" &&
      uuid.test(body.challenge_id)
    )
      return { status: "IF_AUTHORIZED_SENT", challenge_id: body.challenge_id };
    if (operation === "review" && body.status === "OPEN") {
      const details = record(body.details);
      if (
        details &&
        typeof details.request_id === "string" &&
        uuid.test(details.request_id) &&
        typeof details.action === "string" &&
        /^[a-z_]+\.[a-z_]+$/.test(details.action) &&
        typeof details.expires_at === "string" &&
        Number.isFinite(Date.parse(details.expires_at)) &&
        (details.resource_reference === null ||
          (typeof details.resource_reference === "string" &&
            /^[A-Za-z0-9_-]{1,100}$/.test(details.resource_reference)))
      ) {
        return {
          status: "OPEN",
          details: {
            request_id: details.request_id,
            action: details.action,
            resource_reference: details.resource_reference,
            expires_at: details.expires_at,
          },
        };
      }
    }
    if (operation === "decision" && body.status === "RECORDED") {
      const result = record(body.result);
      const approved = value.decision === "APPROVE";
      if (
        result?.status === (approved ? "pending_execution" : "rejected") &&
        result.reason_code ===
          (approved ? "approval_recorded" : "reviewer_rejected")
      ) {
        // The public receipt is deliberately narrower than later execution results.
        return {
          status: "RECORDED",
          result: {
            status: approved ? "pending_execution" : "rejected",
            reason_code: approved ? "approval_recorded" : "reviewer_rejected",
            customer_safe_explanation: approved
              ? "La solicitud fue aprobada y está pendiente de validación y ejecución."
              : "La solicitud no fue aprobada.",
            next_actions: approved ? [] : ["contact_business"],
          },
        };
      }
    }
    return { status: "UNAVAILABLE" };
  } catch {
    // No request bodies, provider errors or proof material in Next error telemetry.
    return { status: "UNAVAILABLE" };
  }
}
