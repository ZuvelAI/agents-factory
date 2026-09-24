import Link from "next/link";
import { notFound } from "next/navigation";

import { StepForm } from "../../../../../../components/onboarding/step-form";
import { StepStatus } from "../../../../../../components/onboarding/step-status";
import { TestAction } from "../../../../../../components/onboarding/test-action";
import { ValidationSummary } from "../../../../../../components/onboarding/validation-summary";
import { Wizard } from "../../../../../../components/onboarding/wizard";
import { UiIcon } from "../../../../../../components/ui-icon";
import { callAuthenticatedBackend } from "../../../../../../lib/api";
import {
  isOnboardingStep,
  type Onboarding,
} from "../../../../../../lib/onboarding";

export default async function OnboardingStepPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string; step: string }>;
  searchParams: Promise<{ saved?: string; error?: string }>;
}) {
  const [{ tenantId, step: stepKey }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  if (!isOnboardingStep(stepKey)) notFound();

  const onboarding = await callAuthenticatedBackend<Onboarding>(
    `/admin/tenants/${encodeURIComponent(tenantId)}/onboarding`,
  );
  const step = onboarding.steps.find((item) => item.key === stepKey);
  if (!step) notFound();
  const previous = onboarding.steps[step.position - 2];
  const next = onboarding.steps[step.position];

  return (
    <section className="onboarding-page" aria-labelledby="onboarding-title">
      <header className="onboarding-header">
        <div>
          <Link className="back-link" href="/">
            <UiIcon name="back" size={15} /> Clientes{" "}
            <span className="breadcrumb-divider">/</span>{" "}
            {onboarding.tenant_name}
          </Link>
          <p className="eyebrow">
            ONBOARDING <span className="eyebrow-separator">/</span> PASO{" "}
            {String(step.position).padStart(2, "0")} DE 12
          </p>
          <div className="title-with-status">
            <h1 id="onboarding-title">
              {step.key === "company" ? "Configura tu empresa" : step.title}
            </h1>
            <StepStatus status={step.status} />
          </div>
          <p>{step.instructions}</p>
        </div>
        <div className="revision-note">
          <UiIcon name="save" size={16} />
          <span>
            {onboarding.updated_at
              ? "Progreso guardado"
              : "Listo para comenzar"}
            <small>Revisión {onboarding.revision}</small>
          </span>
          {onboarding.updated_at ? (
            <small>
              Guardado{" "}
              {new Intl.DateTimeFormat("es-CO", {
                dateStyle: "medium",
                timeStyle: "short",
                timeZone: "America/Bogota",
              }).format(new Date(onboarding.updated_at))}
            </small>
          ) : null}
        </div>
      </header>

      {query.saved === "1" ? (
        <p className="save-notice" role="status">
          Paso guardado correctamente.
        </p>
      ) : null}
      {query.error ? (
        <p className="error-notice" role="alert">
          {query.error === "stale_onboarding_revision"
            ? "Los datos cambiaron en otra sesión. La página se recargó; revisa y vuelve a guardar."
            : "No fue posible guardar el paso. Revisa los campos e inténtalo de nuevo."}
        </p>
      ) : null}

      <div className="wizard-layout">
        <Wizard onboarding={onboarding} activeStep={step.key} />
        <div className="wizard-main">
          <ValidationSummary
            blockers={step.blockers}
            warnings={step.warnings}
          />

          <details className="requirements-card">
            <summary>
              Qué necesitas para este paso{" "}
              <span>{step.required_fields.length} requisitos</span>
            </summary>
            <ul>
              {step.required_fields.map((field) => (
                <li key={field}>{field}</li>
              ))}
            </ul>
          </details>

          <StepForm
            tenantId={tenantId}
            revision={onboarding.revision}
            step={step}
          />
          <TestAction actions={step.test_actions} />

          <div className="documentation-links">
            <strong>Documentación interna</strong>
            {step.documentation_links.map((link) => (
              <a
                href={link.href}
                key={link.href}
                target="_blank"
                rel="noreferrer"
              >
                {link.label}
              </a>
            ))}
          </div>

          <nav className="step-navigation" aria-label="Cambiar paso">
            {previous ? (
              <Link
                className="secondary-link"
                href={`/tenants/${tenantId}/onboarding/${previous.key}`}
              >
                <UiIcon name="back" size={16} /> {previous.title}
              </Link>
            ) : (
              <span />
            )}
            {next ? (
              <Link
                className="button-link"
                href={`/tenants/${tenantId}/onboarding/${next.key}`}
              >
                {next.title} <UiIcon name="arrow" size={16} />
              </Link>
            ) : null}
          </nav>
        </div>
      </div>
    </section>
  );
}
