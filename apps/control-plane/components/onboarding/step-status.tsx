import {
  onboardingStatusLabel,
  type OnboardingStepStatus,
} from "../../lib/onboarding";

export function StepStatus({ status }: { status: OnboardingStepStatus }) {
  return (
    <span
      className={`onboarding-status onboarding-status-${status.toLowerCase()}`}
    >
      {onboardingStatusLabel[status]}
    </span>
  );
}
