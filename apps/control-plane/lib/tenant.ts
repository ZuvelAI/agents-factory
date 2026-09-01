export type Tenant = {
  id: string;
  slug: string;
  name: string;
  legal_name: string | null;
  industry: string | null;
  timezone: string | null;
  locale: "es-CO" | "en-US" | null;
  status: "active" | "suspended";
  revision: number;
  created_at: string;
  updated_at: string;
};

export type AgentSpecVersion = {
  id: string;
  version_number: number;
  state: "DRAFT" | "TEST" | "QUALITY_GATE" | "PRODUCTION";
  created_at: string;
  configuration: {
    persona: {
      business_name: string;
      agent_name: string | null;
      tone: string;
      formality: string;
      brand_vocabulary: string[];
      greeting: string;
    };
    language: {
      supported_locales: ("es-CO" | "en-US")[];
      default_locale: "es-CO" | "en-US";
    };
  };
};

export type AgentEditorState = {
  instance: {
    id: string;
    product: "Agent Customer Service";
  };
  editable_version: AgentSpecVersion;
  production_version: {
    id: string;
    version_number: number;
    state: "PRODUCTION";
    created_at: string;
  } | null;
  quick_options: string[];
};
