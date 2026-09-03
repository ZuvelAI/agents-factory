import Link from "next/link";

import type { OnboardingStep } from "../../lib/onboarding";

export function TestAction({ step }: { step: OnboardingStep }) {
  return (
    <div className="onboarding-actions" aria-label="Step actions">
      {step.test_actions.map((action) =>
        action.available ? (
          <Link className="button-link" href={action.href} key={action.label}>
            {action.label}
          </Link>
        ) : (
          <span
            aria-disabled="true"
            className="onboarding-action-disabled"
            key={action.label}
          >
            {action.label}
          </span>
        ),
      )}
    </div>
  );
}
