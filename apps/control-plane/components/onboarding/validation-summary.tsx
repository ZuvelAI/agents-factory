import type { OnboardingStep } from "../../lib/onboarding";

export function ValidationSummary({ step }: { step: OnboardingStep }) {
  if (!step.blockers.length && !step.warnings.length) {
    return (
      <aside className="onboarding-summary onboarding-summary-clear">
        <h3>Validation summary</h3>
        <p>No blockers detected for this step.</p>
      </aside>
    );
  }

  return (
    <aside className="onboarding-summary" aria-label="Validation summary">
      <h3>Validation summary</h3>
      {step.blockers.map((item) => (
        <p className="onboarding-blocker" key={item.code}>
          <strong>Blocker:</strong> {item.message}
        </p>
      ))}
      {step.warnings.map((item) => (
        <p className="onboarding-warning" key={item.code}>
          <strong>Note:</strong> {item.message}
        </p>
      ))}
    </aside>
  );
}
