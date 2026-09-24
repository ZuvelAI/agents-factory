import type { OnboardingStep } from "../../lib/onboarding";

const labels: Record<OnboardingStep["status"], string> = {
  NOT_STARTED: "Sin iniciar",
  IN_PROGRESS: "En progreso",
  COMPLETE: "Completo",
  BLOCKED: "Bloqueado",
};

export function StepStatus({ status }: { status: OnboardingStep["status"] }) {
  return (
    <span className={`step-status status-${status.toLowerCase()}`}>
      {labels[status]}
    </span>
  );
}
