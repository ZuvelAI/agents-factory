export type CapabilityAction = {
  name: string;
  description: string;
  risk: "LOW" | "MEDIUM" | "HIGH";
  required_identity_level: 0 | 1 | 2 | 3;
  requires_confirmation: boolean;
  requires_approval: boolean;
  required_connector_operations: string[];
  connector_requirement_mode: "single_binding" | "all_bindings" | "none";
};

export type CapabilityManifest = {
  stable_name: string;
  version: string;
  intents: string[];
  workflow: string[];
  actions: CapabilityAction[];
};

export type ConnectionSummary = {
  id: string;
  connector_name: string;
  auth_kind: "OAUTH2" | "API_KEY" | "META_EMBEDDED";
  status: "PENDING" | "CONNECTED" | "REAUTH_REQUIRED" | "REVOKING" | "REVOKED";
  requested_scopes: string[];
  granted_scopes: string[];
  expires_at: string | null;
  health: {
    status: "UNKNOWN" | "HEALTHY" | "REAUTH_REQUIRED" | "ERROR";
    checked_at: string | null;
    error_code: string | null;
  };
};

export type ConnectorCatalogEntry = {
  connector_name: string;
  display_name: string;
  available: boolean;
  availability: "AVAILABLE" | "SETUP_REQUIRED" | "COMING_LATER";
  auth_kind: "OAUTH2" | "API_KEY" | "META_EMBEDDED" | null;
  required_scopes: string[];
  supported_operations: string[];
  connections: ConnectionSummary[];
  note: string;
};

export type ApprovalRoute = {
  id: string;
  revision: number;
  configuration: {
    ref: string;
    capability: string;
    action: string;
    authorized_emails: string[];
    strategy: "first_response";
    enabled: boolean;
    expires_minutes: number;
    otp_seconds: number;
    otp_max_attempts: number;
    otp_max_sends: number;
    otp_cooldown_seconds: number;
  };
};

export type WhatsAppAccount = {
  id: string;
  phone_number_id: string;
  status: string;
  mode: "API_ONLY" | "COEXISTENCE";
  coexistence_eligibility: "ELIGIBLE" | "INELIGIBLE" | "UNKNOWN";
  health_status: "HEALTHY" | "REAUTH_REQUIRED" | "ERROR" | "UNKNOWN";
  verified_at: string | null;
};

export type HandoffConfiguration = {
  account_id: string;
  revision: number;
  configuration: {
    enabled: boolean;
    surface: {
      surface: "WHATSAPP_COEXISTENCE" | "EXTERNAL_INBOX";
      adapter: string;
      binding_id: string;
    } | null;
    inactivity_hours: number;
    timezone: string;
    support_hours: unknown[] | null;
  };
};

export type HumanSurfaceOption = {
  surface: "WHATSAPP_COEXISTENCE" | "EXTERNAL_INBOX";
  adapter: string;
};
