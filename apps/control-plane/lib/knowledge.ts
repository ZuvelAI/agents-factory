export type KnowledgeAuthority = "AUTHORITATIVE" | "SECONDARY" | "REFERENCE";
export type KnowledgeSourceType =
  | "WEBSITE"
  | "PDF"
  | "DOCX"
  | "GOOGLE_DRIVE"
  | "SPREADSHEET"
  | "MANUAL";

export type KnowledgeSource = {
  id: string;
  tenant_id: string;
  name: string;
  source_type: KnowledgeSourceType;
  authority: KnowledgeAuthority;
  configuration: Record<string, unknown>;
  created_at: string;
};

export type KnowledgeIngestion = {
  id: string;
  source_id: string;
  state: "PENDING" | "PROCESSING" | "SUCCEEDED" | "FAILED";
  content_digest: string | null;
  proposed_artifact_count: number;
  error_code: string | null;
  updated_at: string;
};

export type KnowledgeProposal = {
  id: string;
  source_id: string;
  revision: number;
  artifact_type: "FACT" | "DOCUMENT";
  state: "PROPOSED" | "APPROVED" | "EDITED" | "REJECTED";
  proposed_payload: Record<string, unknown>;
  decision_payload: Record<string, unknown> | null;
  proposed_by: "NORMALIZER" | "AI";
  model_metadata: Record<string, unknown>;
  content_digest: string;
  decided_by_admin_id: string | null;
};

export type KnowledgeConflict = {
  id: string;
  proposal_id: string;
  source_id: string;
  fact_key: string | null;
  critical: boolean;
  proposed_authority: KnowledgeAuthority;
  existing_authority: KnowledgeAuthority;
  state: "OPEN" | "RESOLVED";
  resolution: "APPROVED" | "EDITED" | "REJECTED" | null;
  details: Record<string, unknown>;
  created_at: string;
};

export type KnowledgeDiff = {
  id: string;
  source_id: string;
  ingestion_id: string;
  draft_version_id: string;
  previous_digest: string | null;
  current_digest: string;
  state: "DETECTED" | "REVIEWED";
  summary: Record<string, unknown>;
  created_at: string;
};

export type KnowledgeVersionOverview = {
  version: {
    id: string;
    name: string;
    version_number: number;
    state: "DRAFT" | "TEST" | "PRODUCTION";
    digest: string | null;
    based_on_version_id: string | null;
    created_at: string;
    updated_at: string;
  };
  structured_fact_count: number;
  document_count: number;
  candidate_digest: string | null;
  v0_evaluation: "NOT_RUN" | "PASSED" | "FAILED";
  v0_passed_cases: number;
  v0_failed_cases: number;
};

export type KnowledgeWorkspace = {
  sources: {
    source: KnowledgeSource;
    latest_ingestion: KnowledgeIngestion | null;
  }[];
  proposals: KnowledgeProposal[];
  conflicts: KnowledgeConflict[];
  diffs: KnowledgeDiff[];
  versions: KnowledgeVersionOverview[];
  production_blocker_code: "production_quality_gate_required";
  production_blocker: string;
};
