import Link from "next/link";

import type { OnboardingStatus } from "../../lib/onboarding";
import { StepStatus } from "./step-status";

export function OnboardingWizard({
  status,
  currentSlug,
}: {
  status: OnboardingStatus;
  currentSlug: string;
}) {
  return (
    <aside className="onboarding-wizard">
      <div className="onboarding-progress">
        <p className="eyebrow">Canonical setup</p>
        <strong>{status.complete_steps} of 12 complete</strong>
        <progress max={12} value={status.complete_steps}>
          {status.complete_steps} of 12
        </progress>
      </div>
      <nav aria-label="Tenant onboarding steps">
        <ol className="onboarding-step-list">
          {status.steps.map((step) => (
            <li key={step.slug}>
              <Link
                aria-current={step.slug === currentSlug ? "step" : undefined}
                href={`/tenants/${status.tenant_id}/onboarding/${step.slug}`}
              >
                <span>
                  {step.number}. {step.name}
                </span>
                <StepStatus status={step.status} />
              </Link>
            </li>
          ))}
        </ol>
      </nav>
    </aside>
  );
}
