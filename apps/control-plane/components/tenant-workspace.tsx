import Link from "next/link";

import { callAuthenticatedBackend } from "../lib/api";

type Tenant = {
  id: string;
  slug: string;
  name: string;
  status: "active" | "suspended";
};

export async function TenantWorkspace({
  title,
  description,
  emptyMessage,
  onboardingStep,
  actionLabel = "Abrir configuración",
}: {
  title: string;
  description: string;
  emptyMessage?: string;
  onboardingStep?: string;
  actionLabel?: string;
}) {
  let tenants: Tenant[] = [];
  let backendAvailable = true;
  try {
    tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  } catch {
    backendAvailable = false;
  }

  return (
    <section className="workspace-page" aria-labelledby="workspace-title">
      <p className="eyebrow">Control Plane</p>
      <h1 id="workspace-title">{title}</h1>
      <p className="workspace-description">{description}</p>

      {!backendAvailable ? (
        <p className="connection-notice" role="status">
          El backend local no está disponible.
        </p>
      ) : null}

      {emptyMessage ? (
        <div className="workspace-empty">
          <strong>Estado actual</strong>
          <p>{emptyMessage}</p>
        </div>
      ) : null}

      {onboardingStep ? (
        <div className="tenant-grid">
          {tenants.map((tenant) => (
            <article className="tenant-card" key={tenant.id}>
              <div>
                <span className={`tenant-state tenant-state-${tenant.status}`}>
                  {tenant.status === "active" ? "Activo" : "Suspendido"}
                </span>
                <h2>{tenant.name}</h2>
                <p>{tenant.slug}</p>
              </div>
              <Link
                className="button-link"
                href={`/tenants/${tenant.id}/onboarding/${onboardingStep}`}
              >
                {actionLabel}
              </Link>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
