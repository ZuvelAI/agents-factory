export type OnboardingStepStatus =
  | "COMPLETE"
  | "READY"
  | "BLOCKED"
  | "ATTENTION"
  | "STALE"
  | "UNAVAILABLE";

export type OnboardingMessage = {
  code: string;
  message: string;
};

export type OnboardingStep = {
  number: number;
  slug: string;
  name: string;
  instructions: string[];
  required_fields: string[];
  validations: string[];
  status: OnboardingStepStatus;
  blockers: OnboardingMessage[];
  warnings: OnboardingMessage[];
  test_actions: { label: string; href: string; available: boolean }[];
  documentation: { label: string; href: string }[];
};

export type OnboardingStatus = {
  tenant_id: string;
  agent_instance_id: string | null;
  agent_version_id: string | null;
  agent_version_number: number | null;
  complete_steps: number;
  current_step_slug: string;
  classifications: (
    | "STANDARD"
    | "CUSTOM_CONNECTOR"
    | "CUSTOM_WORKFLOW"
    | "NEW_CAPABILITY"
  )[];
  steps: OnboardingStep[];
};

export const onboardingStatusLabel: Record<OnboardingStepStatus, string> = {
  COMPLETE: "Complete",
  READY: "Ready",
  BLOCKED: "Blocked",
  ATTENTION: "Needs attention",
  STALE: "Stale",
  UNAVAILABLE: "Unavailable",
};
