import Link from "next/link";

import type { Onboarding, OnboardingStepKey } from "../../lib/onboarding";
import { StepStatus } from "./step-status";
import { UiIcon } from "../ui-icon";

export function Wizard({
  onboarding,
  activeStep,
}: {
  onboarding: Onboarding;
  activeStep: OnboardingStepKey;
}) {
  const percent = Math.round(
    (onboarding.completed_steps / onboarding.total_steps) * 100,
  );

  return (
    <aside className="wizard-sidebar" aria-label="Pasos de onboarding">
      <div className="wizard-progress">
        <span className="eyebrow">TU AGENTE, PASO A PASO</span>
        <div className="progress-caption">
          <strong>Configuración</strong>
          <span>
            {onboarding.completed_steps}
            <span className="muted"> / {onboarding.total_steps}</span>
          </span>
        </div>
        <div
          className="progress-track"
          role="progressbar"
          aria-label="Progreso del onboarding"
          aria-valuenow={onboarding.completed_steps}
          aria-valuemin={0}
          aria-valuemax={onboarding.total_steps}
        >
          <span style={{ width: `${percent}%` }} />
        </div>
      </div>
      <ol>
        {onboarding.steps.map((step) => (
          <li key={step.key}>
            <Link
              href={`/tenants/${onboarding.tenant_id}/onboarding/${step.key}`}
              aria-current={step.key === activeStep ? "step" : undefined}
              className={step.key === activeStep ? "active" : undefined}
            >
              <span className="step-number">
                {step.status === "COMPLETE" ? (
                  <UiIcon name="check" size={15} />
                ) : (
                  String(step.position).padStart(2, "0")
                )}
              </span>
              <span className="wizard-step-copy">
                <span className="wizard-step-title">{step.title}</span>
                <StepStatus status={step.status} />
              </span>
              {step.key === activeStep ? (
                <UiIcon name="chevron" size={14} />
              ) : null}
            </Link>
          </li>
        ))}
      </ol>
      <p className="wizard-resume-note">
        <UiIcon name="save" size={16} /> Guarda cada paso y continúa cuando
        quieras.
      </p>
    </aside>
  );
}
