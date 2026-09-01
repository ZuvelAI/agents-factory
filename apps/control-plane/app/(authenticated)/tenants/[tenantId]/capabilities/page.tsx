import Link from "next/link";

import { updateTenantCapabilities } from "../../../../actions";
import { VersionBanner } from "../../../../../components/agents/version-banner";
import { ApprovalRouteForm } from "../../../../../components/configuration/approval-route-form";
import { CapabilityCard } from "../../../../../components/configuration/capability-card";
import { IdentityMatrix } from "../../../../../components/configuration/identity-matrix";
import { RiskMatrix } from "../../../../../components/configuration/risk-matrix";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import type {
  ApprovalRoute,
  CapabilityAction,
  CapabilityManifest,
} from "../../../../../lib/configuration";
import type { AgentEditorState } from "../../../../../lib/tenant";

export default async function TenantCapabilitiesPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ error?: string; saved?: string }>;
}) {
  const { tenantId } = await params;
  const query = await searchParams;
  const [agent, manifests, routes] = await Promise.all([
    callAuthenticatedBackend<AgentEditorState | null>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/current`,
    ),
    callAuthenticatedBackend<CapabilityManifest[]>("/admin/capabilities"),
    callAuthenticatedBackend<ApprovalRoute[]>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/approvals/routes`,
    ),
  ]);

  if (agent === null) {
    return (
      <section className="tenant-section state-panel">
        <span className="state-symbol" aria-hidden="true">
          1
        </span>
        <h2>Create the Agent Draft first</h2>
        <p>Capabilities are versioned inside each tenant AgentSpec.</p>
        <Link className="button-link" href={`/tenants/${tenantId}/agent`}>
          Configure agent
        </Link>
      </section>
    );
  }

  const configuration = agent.editable_version.configuration;
  const enabledNames = new Set(
    configuration.capabilities.map((item) => item.name),
  );
  const boundOperations = new Set(
    configuration.connector_bindings.flatMap((binding) => binding.operations),
  );
  const enabledActions: CapabilityAction[] = manifests
    .filter((manifest) => enabledNames.has(manifest.stable_name))
    .flatMap((manifest) => manifest.actions);

  return (
    <section className="tenant-section configuration-page">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Guided setup</p>
        <h2>Capabilities and policies</h2>
        <p>
          Choose approved capability packs, then make action controls stricter
          where this client requires it.
        </p>
      </header>
      <ConfigurationNotice error={query.error} saved={query.saved} />
      <VersionBanner
        currentState={agent.editable_version.state}
        currentVersion={agent.editable_version.version_number}
        productionVersion={agent.production_version?.version_number ?? null}
      />
      <form action={updateTenantCapabilities} className="configuration-form">
        <input type="hidden" name="tenantId" value={tenantId} />
        <input type="hidden" name="instanceId" value={agent.instance.id} />
        <input
          type="hidden"
          name="versionId"
          value={agent.editable_version.id}
        />
        <div className="configuration-grid">
          {manifests.map((manifest) => (
            <CapabilityCard
              boundOperations={boundOperations}
              enabled={enabledNames.has(manifest.stable_name)}
              key={manifest.stable_name}
              manifest={manifest}
            />
          ))}
        </div>
        <div className="form-actions">
          <button type="submit">Save capabilities as Draft</button>
        </div>
      </form>

      {enabledActions.length ? (
        <>
          <IdentityMatrix actions={enabledActions} />
          <RiskMatrix
            actions={enabledActions}
            agent={agent}
            tenantId={tenantId}
          />
          <ApprovalRouteForm
            actions={enabledActions}
            agent={agent}
            routes={routes}
            tenantId={tenantId}
          />
        </>
      ) : (
        <p className="coming-step">
          Enable at least one capability to configure its action policies.
        </p>
      )}
    </section>
  );
}

function ConfigurationNotice({
  error,
  saved,
}: {
  error?: string;
  saved?: string;
}) {
  if (error) {
    return (
      <p className="form-notice form-notice-error" role="alert">
        {error === "stale"
          ? "A newer Draft exists. Review it before saving again."
          : "The configuration could not be saved."}
      </p>
    );
  }
  return saved ? (
    <p className="form-notice form-notice-success" role="status">
      Saved as a new Agent Draft.
    </p>
  ) : null;
}
