import Link from "next/link";

import { callAuthenticatedBackend } from "../../../lib/api";
import type { Tenant } from "../../../lib/tenant";

export default async function IntegrationsPage() {
  const tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");

  return (
    <section className="narrow-page configuration-page">
      <header className="page-heading">
        <p className="eyebrow">Tenant-owned connections</p>
        <h1>Integrations</h1>
        <p>
          Connections, permissions and health are isolated per tenant. Select a
          client to configure its supported providers.
        </p>
      </header>
      <div className="tenant-card-grid">
        {tenants.map((tenant) => (
          <article className="tenant-card" key={tenant.id}>
            <p className="eyebrow">{tenant.slug}</p>
            <h2>{tenant.name}</h2>
            <p>Review connections, operation mappings and human surfaces.</p>
            <Link
              className="button-link"
              href={`/tenants/${tenant.id}/integrations`}
            >
              Configure integrations
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}
