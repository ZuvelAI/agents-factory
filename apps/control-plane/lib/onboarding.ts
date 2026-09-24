export const onboardingStepKeys = [
  "company",
  "agent",
  "capabilities",
  "integrations",
  "knowledge",
  "policies-identity",
  "human-operations",
  "approval-routes",
  "whatsapp",
  "test",
  "quality-gate",
  "production",
] as const;

export type OnboardingStepKey = (typeof onboardingStepKeys)[number];
export type OnboardingStep = {
  key: OnboardingStepKey;
  position: number;
  title: string;
  instructions: string;
  status: "NOT_STARTED" | "IN_PROGRESS" | "COMPLETE" | "BLOCKED";
  required_fields: string[];
  test_actions: string[];
  blockers: string[];
  warnings: string[];
  documentation_links: { label: string; href: string }[];
  data: Record<string, unknown>;
};

export type Onboarding = {
  tenant_id: string;
  tenant_name: string;
  revision: number;
  updated_at: string | null;
  current_step: OnboardingStepKey;
  completed_steps: number;
  total_steps: 12;
  steps: OnboardingStep[];
};

export function isOnboardingStep(value: string): value is OnboardingStepKey {
  return onboardingStepKeys.includes(value as OnboardingStepKey);
}
