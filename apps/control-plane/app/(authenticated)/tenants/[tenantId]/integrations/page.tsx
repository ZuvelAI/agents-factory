import Link from "next/link";

import { VersionBanner } from "../../../../../components/agents/version-banner";
import { ConnectorCard } from "../../../../../components/configuration/connector-card";
import { HandoffForm } from "../../../../../components/configuration/handoff-form";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import type {
  ConnectorCatalogEntry,
  HandoffConfiguration,
  HumanSurfaceOption,
  WhatsAppAccount,
} from "../../../../../lib/configuration";
import type { AgentEditorState, Tenant } from "../../../../../lib/tenant";

export default async function TenantIntegrationsPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ error?: string; saved?: string }>;
}) {
  const { tenantId } = await params;
  const query = await searchParams;
  const [tenant, agent, catalog, accounts, configurations, surfaces] =
    await Promise.all([
      callAuthenticatedBackend<Tenant>(
        `/admin/tenants/${encodeURIComponent(tenantId)}`,
      ),
      callAuthenticatedBackend<AgentEditorState | null>(
        `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/current`,
      ),
      callAuthenticatedBackend<ConnectorCatalogEntry[]>(
        `/admin/tenants/${encodeURIComponent(tenantId)}/integrations/catalog`,
      ),
      callAuthenticatedBackend<WhatsAppAccount[]>(
        `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp`,
      ),
      callAuthenticatedBackend<HandoffConfiguration[]>(
        `/admin/tenants/${encodeURIComponent(tenantId)}/handoffs/configurations`,
      ),
      callAuthenticatedBackend<HumanSurfaceOption[]>(
        `/admin/tenants/${encodeURIComponent(tenantId)}/handoffs/surfaces`,
      ),
    ]);

  if (agent === null) {
    return (
      <section className="tenant-section state-panel">
        <span className="state-symbol" aria-hidden="true">
          1
        </span>
        <h2>Create the Agent Draft first</h2>
        <p>Connector mappings are versioned inside the tenant AgentSpec.</p>
        <Link className="button-link" href={`/tenants/${tenantId}/agent`}>
          Configure agent
        </Link>
      </section>
    );
  }

  return (
    <section className="tenant-section configuration-page">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Guided setup</p>
        <h2>Integrations and human operations</h2>
        <p>
          Connect tenant-owned accounts, expose only supported operations and
          keep health failures isolated from healthy capabilities.
        </p>
      </header>
      {query.error ? (
        <p className="form-notice form-notice-error" role="alert">
          {query.error === "stale"
            ? "A newer Draft exists. Review it before saving again."
            : "The integration change could not be saved."}
        </p>
      ) : query.saved ? (
        <p className="form-notice form-notice-success" role="status">
          Integration configuration saved.
        </p>
      ) : null}
      <VersionBanner
        currentState={agent.editable_version.state}
        currentVersion={agent.editable_version.version_number}
        productionVersion={agent.production_version?.version_number ?? null}
      />
      <div className="configuration-grid connector-grid">
        {catalog.map((entry) => (
          <ConnectorCard
            agent={agent}
            entry={entry}
            key={entry.connector_name}
            tenantId={tenantId}
          />
        ))}
      </div>
      <HandoffForm
        accounts={accounts}
        agent={agent}
        configurations={configurations}
        surfaces={surfaces}
        tenant={tenant}
      />
    </section>
  );
}
