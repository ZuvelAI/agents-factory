import Link from "next/link";

import { callAuthenticatedBackend } from "../../lib/api";

type Tenant = {
  id: string;
  slug: string;
  name: string;
  status: "active" | "suspended";
};

export default async function DashboardPage() {
  let tenants: Tenant[] = [];
  let backendAvailable = true;
  try {
    tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  } catch {
    backendAvailable = false;
  }

  return (
    <section className="dashboard" aria-labelledby="dashboard-title">
      <p className="eyebrow">Control Plane</p>
      <h1 id="dashboard-title">Clientes</h1>
      <p>Configura cada agente mediante el onboarding guiado y resumible.</p>
      {!backendAvailable ? (
        <p className="connection-notice" role="status">
          El backend local no está disponible.
        </p>
      ) : null}
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
              href={`/tenants/${tenant.id}/onboarding/company`}
            >
              Abrir onboarding
            </Link>
            <Link
              className="button-link"
              href={`/tenants/${tenant.id}/whatsapp`}
            >
              Configurar WhatsApp
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}
