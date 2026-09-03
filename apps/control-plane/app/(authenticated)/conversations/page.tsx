import Link from "next/link";

import { callAuthenticatedBackend } from "../../../lib/api";
import type { Tenant } from "../../../lib/tenant";

export default async function ConversationsPage() {
  const tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  return (
    <section className="narrow-page conversation-page">
      <header className="page-heading list-heading">
        <div>
          <p className="eyebrow">Review and learning</p>
          <h1>Conversations</h1>
          <p>
            Inspect attributable client conversations and create reviewed
            regression Drafts.
          </p>
        </div>
        <Link className="button-link" href="/test-console">
          Open Test Console
        </Link>
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
              href={`/tenants/${tenant.id}/conversations`}
            >
              Review conversations
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}
