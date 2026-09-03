export type ReviewCategory =
  | "AI_RESOLVED"
  | "HUMAN_HANDOFF"
  | "TOOL_FAILURE"
  | "POLICY_VIOLATION"
  | "COMPLAINT"
  | "HIGH_COST"
  | "FLAGGED";
export type ReviewLabel =
  | "CORRECT"
  | "INCORRECT"
  | "UNSAFE"
  | "KNOWLEDGE_PROBLEM"
  | "INTEGRATION_PROBLEM"
  | "MODEL_REASONING_PROBLEM";
export type TestMode = "SANDBOX_SIMULATED" | "REAL_TEST_ENVIRONMENT";

export type ConversationReview = {
  id: string;
  conversation_id: string;
  revision: number;
  categories: ReviewCategory[];
  labels: ReviewLabel[];
  note: string | null;
  updated_at: string;
};

export type ConversationOverview = {
  id: string;
  customer_reference: string;
  control_state: string;
  message_count: number;
  opened_at: string;
  latest_message_at: string | null;
  review: ConversationReview | null;
};

export type EvalCaseDraft = {
  id: string;
  conversation_id: string;
  case_id: string;
  schema_version: 1;
  payload: Record<string, unknown>;
  status: "DRAFT";
  created_at: string;
};

export type ConversationWorkspace = {
  conversations: ConversationOverview[];
  eval_drafts: EvalCaseDraft[];
  categories: ReviewCategory[];
  labels: ReviewLabel[];
};

export type TimelineMessage = {
  id: string;
  direction: string;
  sender_type: string;
  message_type: string;
  text: string;
  occurred_at: string;
  agent_spec_id: string | null;
  agent_spec_version: string | null;
  runtime_metadata: Record<string, unknown>;
};

export type ConversationDetail = {
  conversation: ConversationOverview;
  messages: TimelineMessage[];
};

export type TestReadiness = {
  sandbox_available: true;
  real_test_available: boolean;
  real_test_reason: string | null;
};

export type TestRunInspector = {
  id: string;
  tenant_id: string;
  mode: TestMode;
  simulated: boolean;
  response: string;
  agent_spec: Record<string, unknown>;
  knowledge: Record<string, unknown> | null;
  intent: string;
  capability: string;
  identity: Record<string, unknown>;
  tools: Record<string, unknown>[];
  sources: Record<string, unknown>[];
  action: Record<string, unknown>;
  approval: Record<string, unknown>;
  usage: Record<string, unknown>;
  latency_ms: number;
  trace_id: string;
  created_at: string;
};
