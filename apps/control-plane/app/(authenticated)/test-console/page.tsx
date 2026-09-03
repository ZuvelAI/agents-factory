import Link from "next/link";

import { callAuthenticatedBackend } from "../../../lib/api";
import type { Tenant } from "../../../lib/tenant";

export default async function TestConsolePage() {
  const tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  return (
    <section className="narrow-page test-console-page">
      <header className="page-heading">
        <p className="eyebrow">Safe execution</p>
        <h1>Test Console</h1>
        <p>
          Run the shared Agent configuration with simulated tools or a
          separately configured real test environment.
        </p>
      </header>
      <div className="tenant-card-grid">
        {tenants.map((tenant) => (
          <article className="tenant-card" key={tenant.id}>
            <h2>{tenant.name}</h2>
            <p>Agent and Knowledge versions remain tenant-bound.</p>
            <Link
              className="text-link"
              href={`/tenants/${tenant.id}/test-console`}
            >
              Open safe console
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}
