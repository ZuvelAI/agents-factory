import Link from "next/link";

import { EmptyState } from "../../../components/empty-state";
import { ErrorState } from "../../../components/error-state";
import { BackendProblem, callAuthenticatedBackend } from "../../../lib/api";
import type { Tenant } from "../../../lib/tenant";

export default async function TenantsPage() {
  let tenants: Tenant[];
  try {
    tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  } catch (error) {
    return (
      <div className="dashboard-page">
        <ErrorState
          title="Tenants unavailable"
          description="The tenant directory could not be loaded."
          correlationId={
            error instanceof BackendProblem ? error.correlationId : undefined
          }
        />
      </div>
    );
  }

  return (
    <div className="dashboard-page">
      <header className="page-heading list-heading">
        <div>
          <p className="eyebrow">Client environments</p>
          <h1>Tenants</h1>
          <p>Resume each client&apos;s guided setup and release workflow.</p>
        </div>
        <Link className="button-link" href="/tenants/new">
          Create tenant
        </Link>
      </header>
      {tenants.length === 0 ? (
        <EmptyState
          title="No tenants yet"
          description="Create the first tenant to begin its guided configuration."
          action={{ label: "Create first tenant", href: "/tenants/new" }}
        />
      ) : (
        <div className="tenant-card-grid">
          {tenants.map((tenant) => (
            <article className="tenant-card" key={tenant.id}>
              <div>
                <span
                  className={`tenant-status tenant-status-${tenant.status}`}
                >
                  {tenant.status}
                </span>
                <h2>{tenant.name}</h2>
                <p>{tenant.industry ?? "Industry pending"}</p>
              </div>
              <dl>
                <div>
                  <dt>Locale</dt>
                  <dd>{tenant.locale ?? "Pending"}</dd>
                </div>
                <div>
                  <dt>Timezone</dt>
                  <dd>{tenant.timezone ?? "Pending"}</dd>
                </div>
              </dl>
              <Link className="text-link" href={`/tenants/${tenant.id}`}>
                Continue setup
              </Link>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
