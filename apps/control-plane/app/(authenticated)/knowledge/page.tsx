import Link from "next/link";

import { callAuthenticatedBackend } from "../../../lib/api";
import type { Tenant } from "../../../lib/tenant";

export default async function KnowledgePage() {
  const tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  return (
    <section className="narrow-page knowledge-page">
      <header className="page-heading">
        <p className="eyebrow">Human-reviewed Knowledge</p>
        <h1>Knowledge workspaces</h1>
        <p>
          Open a client workspace to synchronize sources, review every proposal,
          and promote an exact version through Draft and Test.
        </p>
      </header>
      <div className="tenant-card-grid">
        {tenants.map((tenant) => (
          <article className="tenant-card" key={tenant.id}>
            <span className={`tenant-status tenant-status-${tenant.status}`}>
              {tenant.status}
            </span>
            <h2>{tenant.name}</h2>
            <p>{tenant.industry ?? "Industry pending"}</p>
            <Link
              className="text-link"
              href={`/tenants/${tenant.id}/knowledge`}
            >
              Review Knowledge
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}
