import Link from "next/link";
import { notFound } from "next/navigation";

import { TestAction } from "../../../../../../components/onboarding/test-action";
import { StepStatus } from "../../../../../../components/onboarding/step-status";
import { ValidationSummary } from "../../../../../../components/onboarding/validation-summary";
import { OnboardingWizard } from "../../../../../../components/onboarding/wizard";
import { callAuthenticatedBackend } from "../../../../../../lib/api";
import type { OnboardingStatus } from "../../../../../../lib/onboarding";

export default async function OnboardingStepPage({
  params,
}: {
  params: Promise<{ tenantId: string; step: string }>;
}) {
  const { tenantId, step: stepSlug } = await params;
  const status = await callAuthenticatedBackend<OnboardingStatus>(
    `/admin/tenants/${encodeURIComponent(tenantId)}/onboarding`,
  );
  const step = status.steps.find((candidate) => candidate.slug === stepSlug);
  if (!step) notFound();

  const previous = status.steps[step.number - 2];
  const next = status.steps[step.number];
  return (
    <section className="onboarding-shell">
      <OnboardingWizard currentSlug={step.slug} status={status} />
      <article className="onboarding-step-detail">
        <header className="onboarding-step-heading">
          <div>
            <p className="eyebrow">Step {step.number} of 12</p>
            <h2>{step.name}</h2>
          </div>
          <StepStatus status={step.status} />
        </header>

        <div className="onboarding-instructions">
          {step.instructions.map((instruction) => (
            <p key={instruction}>{instruction}</p>
          ))}
        </div>

        {step.slug === "capabilities" ? (
          <section className="classification-panel">
            <h3>Unsupported request classification</h3>
            <p>
              Record unsupported needs as one of the approved extension classes;
              do not add tenant-specific product behavior here.
            </p>
            <ul>
              {status.classifications.map((classification) => (
                <li key={classification}>
                  {classification.replaceAll("_", " ")}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <div className="onboarding-requirements">
          <section>
            <h3>Required fields</h3>
            <ul>
              {step.required_fields.map((field) => (
                <li key={field}>{field}</li>
              ))}
            </ul>
          </section>
          <section>
            <h3>Validation</h3>
            <ul>
              {step.validations.map((validation) => (
                <li key={validation}>{validation}</li>
              ))}
            </ul>
          </section>
        </div>

        <ValidationSummary step={step} />
        <TestAction step={step} />

        <section className="onboarding-docs">
          <h3>Internal documentation</h3>
          <ul>
            {step.documentation.map((document) => (
              <li key={document.href}>
                <a href={document.href}>{document.label}</a>
              </li>
            ))}
          </ul>
        </section>

        <nav
          className="onboarding-pagination"
          aria-label="Onboarding pagination"
        >
          {previous ? (
            <Link href={`/tenants/${tenantId}/onboarding/${previous.slug}`}>
              ← {previous.name}
            </Link>
          ) : (
            <span />
          )}
          {next ? (
            <Link href={`/tenants/${tenantId}/onboarding/${next.slug}`}>
              {next.name} →
            </Link>
          ) : (
            <span />
          )}
        </nav>
      </article>
    </section>
  );
}
