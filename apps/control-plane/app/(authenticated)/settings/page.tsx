import Link from "next/link";

import { callAuthenticatedBackend } from "../../../lib/api";
import type { Tenant } from "../../../lib/tenant";

export default async function SettingsPage() {
  const tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  return (
    <section className="narrow-page settings-page">
      <header className="page-heading">
        <p className="eyebrow">Configuration ownership</p>
        <h1>Settings</h1>
        <p>
          Client configuration stays in guided tenant forms. Deployment secrets,
          environment variables and arbitrary shell access are not exposed here.
        </p>
      </header>
      <div className="operational-grid">
        {tenants.map((tenant) => (
          <article className="operational-card" key={tenant.id}>
            <span className={`tenant-status tenant-status-${tenant.status}`}>
              {tenant.status}
            </span>
            <h2>{tenant.name}</h2>
            <p>
              Business profile, locale and regional defaults are revision
              protected.
            </p>
            <Link
              className="button-link"
              href={`/tenants/${tenant.id}/settings`}
            >
              Open tenant settings
            </Link>
          </article>
        ))}
      </div>
      <section className="operational-card unavailable-card">
        <span className="review-state review-unavailable">
          Deployment-owned
        </span>
        <h2>Runtime and Production settings</h2>
        <p>
          Task 47 owns hardened environments, deployment promotion, rollback and
          measured infrastructure. No unverified setting is editable in MS7.
        </p>
        <button disabled type="button">
          Production settings unavailable
        </button>
      </section>
    </section>
  );
}
