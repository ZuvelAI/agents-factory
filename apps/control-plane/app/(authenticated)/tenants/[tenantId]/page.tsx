import Link from "next/link";

import { callAuthenticatedBackend } from "../../../../lib/api";
import type { OnboardingStatus } from "../../../../lib/onboarding";
import type { AgentEditorState, Tenant } from "../../../../lib/tenant";

export default async function TenantOverviewPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  const [tenant, agent, onboarding] = await Promise.all([
    callAuthenticatedBackend<Tenant>(
      `/admin/tenants/${encodeURIComponent(tenantId)}`,
    ),
    callAuthenticatedBackend<AgentEditorState | null>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/current`,
    ),
    callAuthenticatedBackend<OnboardingStatus>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/onboarding`,
    ),
  ]);
  const profileComplete = Boolean(
    tenant.legal_name && tenant.industry && tenant.timezone && tenant.locale,
  );
  return (
    <section className="tenant-section">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Configuration progress</p>
        <h2>Overview</h2>
        <p>
          Continue from the next incomplete step. Progress is saved per tenant.
        </p>
      </header>
      <div className="onboarding-resume">
        <div>
          <span className="step-done">
            {onboarding.complete_steps} of 12 complete
          </span>
          <h3>Canonical onboarding</h3>
          <p>
            Resume at the first step derived from the tenant&apos;s saved
            configuration.
          </p>
        </div>
        <Link
          className="button-link"
          href={`/tenants/${tenantId}/onboarding/${onboarding.current_step_slug}`}
        >
          Continue onboarding
        </Link>
      </div>
      <div className="progress-grid">
        <article>
          <span className={profileComplete ? "step-done" : "step-pending"}>
            {profileComplete ? "Complete" : "Pending"}
          </span>
          <h3>Business profile</h3>
          <p>Identity, industry, locale and timezone.</p>
          <Link href={`/tenants/${tenantId}/settings`}>Review profile</Link>
        </article>
        <article>
          <span className={agent ? "step-done" : "step-pending"}>
            {agent
              ? `Draft v${agent.editable_version.version_number}`
              : "Pending"}
          </span>
          <h3>Agent presentation</h3>
          <p>Name, voice, greeting and approved languages.</p>
          <Link href={`/tenants/${tenantId}/agent`}>Configure agent</Link>
        </article>
      </div>
    </section>
  );
}
