export type CasePriority = "LOW" | "NORMAL" | "HIGH" | "CRITICAL";

export type CaseSummary = {
  id: string;
  capability: string;
  issue_type: string;
  revision: number;
  status: string;
  priority: CasePriority;
  target_status: string;
  target_at: string;
  reviewer_reference: string;
  approval_status: string;
  latest_event: string | null;
  latest_reason: string | null;
  updated_at: string;
};

export type CaseWorkspace = {
  generated_at: string;
  cases: CaseSummary[];
  page: number;
  limit: number;
  total: number;
  has_more: boolean;
};

export type QualityGateOverview = {
  available: true;
  exact_version_required: true;
  latest: null | {
    id: string;
    eval_run_id: string;
    passed: boolean;
    agent_spec_digest: string;
    knowledge_digest: string;
    code_digest: string;
    hard_blockers: string[];
    passed_cases: number;
    failed_cases: number;
    runner_version: string;
    decided_at: string;
  };
};

export type OperationsWorkspace = {
  generated_at: string;
  state: "HEALTHY" | "ACTIVE" | "IDLE" | "DEGRADED" | "UNKNOWN";
  topics: {
    topic: string;
    pending: number;
    processing: number;
    failed: number;
    dead_letter: number;
    oldest_pending_at: string | null;
    state: "HEALTHY" | "ACTIVE" | "IDLE" | "DEGRADED" | "UNKNOWN";
    state_basis: "RECORDED_QUEUE_STATE";
  }[];
  integrations: {
    id: string;
    connector_name: string;
    connection_status: string;
    health_status: string;
    last_health_checked_at: string | null;
    last_error_code: string | null;
  }[];
  dead_letters: {
    id: string;
    outbox_job_id: string;
    topic: string;
    reason_code: string;
    status: "open" | "resolved" | "discarded";
    attempt_count: number;
    max_attempts: number;
    last_error_code: string | null;
    created_at: string;
    updated_at: string;
  }[];
  dead_letter_page: number;
  dead_letter_has_more: boolean;
  recent_audit: {
    event_type: string;
    entity_id: string | null;
    correlation_id: string;
    occurred_at: string;
  }[];
  health: {
    generated_at: string;
    state: "HEALTHY" | "DEGRADED" | "DOWN" | "UNKNOWN";
    components: {
      component: string;
      state: "HEALTHY" | "DEGRADED" | "DOWN" | "UNKNOWN";
      observed_at: string | null;
      reason_code: string | null;
    }[];
  };
  incidents: {
    id: string;
    incident_type: string;
    severity: "WARNING" | "ERROR" | "CRITICAL";
    status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
    title: string;
    correlation_id: string;
    occurrence_count: number;
    first_detected_at: string;
    last_detected_at: string;
    evidence_until: string;
  }[];
  quality_gate: QualityGateOverview;
  deployments: {
    available: true;
    promotion_mode: "GITHUB_ENVIRONMENT_APPROVAL";
    latest: {
      id: string;
      environment: "STAGING" | "PRODUCTION";
      release_version: string;
      backend_image_digest: string;
      control_plane_image_digest: string;
      migration_version: string;
      status:
        | "PENDING"
        | "MIGRATING"
        | "PROMOTING"
        | "HEALTHY"
        | "FAILED"
        | "ROLLED_BACK";
      quality_gate_decision_id: string;
      correlation_id: string;
      started_at: string;
      completed_at: string | null;
    }[];
  };
};

export type UsageDimension = "tenant" | "conversation" | "case" | "action";

export type UsageSummary = {
  dimension: UsageDimension;
  groups: {
    group: string | null;
    currency: string;
    records: number;
    known_cost: string;
    unknown_cost_records: number;
    input_tokens: string | null;
    cached_input_tokens: string | null;
    output_tokens: string | null;
    reasoning_tokens: string | null;
    requests: string | null;
    average_latency_ms: string | null;
    complete_cost: boolean;
  }[];
  has_more: boolean;
  recorded_data_only: true;
};

export type UsageFreshness = {
  generated_at: string;
  latest_recorded_at: string | null;
  records: number;
  state: "fresh" | "stale" | "empty";
};

export type MarginEstimate = {
  currency: string;
  revenue: string;
  variable_cost: string | null;
  gross_profit: string | null;
  gross_margin_percent: string | null;
  reason: "mixed_currency" | "unknown_cost" | null;
};
