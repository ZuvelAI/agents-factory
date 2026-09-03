export type ReviewDetails = {
  request_id: string;
  action: string;
  resource_reference: string | null;
  expires_at: string;
};

export type ReviewResult = {
  status: "pending_execution" | "rejected";
  reason_code: "approval_recorded" | "reviewer_rejected";
  customer_safe_explanation: string;
  next_actions: string[];
};

export type ApprovalReply =
  | { status: "OPEN"; details?: ReviewDetails }
  | { status: "IF_AUTHORIZED_SENT"; challenge_id: string }
  | { status: "RECORDED"; result: ReviewResult }
  | {
      status:
        | "CLOSED"
        | "INVALID_VERIFICATION"
        | "UNAVAILABLE"
        | "RATE_LIMITED";
    };

export const APPROVAL_REASONS = {
  customer_request: "Solicitud del cliente revisada",
  reviewer_rejected: "Solicitud no aprobada",
  order_already_shipped: "El pedido ya fue despachado",
  appointment_already_cancelled: "La cita ya estaba cancelada",
  policy_restriction: "La política del negocio no lo permite",
  insufficient_information: "Falta información para autorizar",
} as const;

export const ACTION_LABELS: Record<string, string> = {
  "orders.request_order_cancellation": "Solicitud de cancelación de pedido",
  "appointments.request_cancellation": "Solicitud de cancelación de cita",
};

export const LINK_PATTERN =
  /^a1\.[a-f0-9]{32}\.[a-f0-9]{32}\.[a-f0-9]{32}\.[0-9]{1,11}\.[a-f0-9]{64}$/;
