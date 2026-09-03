import { createCustomerServiceDraft } from "../../../../actions";
import { LanguageForm } from "../../../../../components/agents/language-form";
import { PersonaForm } from "../../../../../components/agents/persona-form";
import { VersionBanner } from "../../../../../components/agents/version-banner";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import type { AgentEditorState, Tenant } from "../../../../../lib/tenant";

export default async function TenantAgentPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ created?: string; error?: string; saved?: string }>;
}) {
  const { tenantId } = await params;
  const query = await searchParams;
  const [tenant, agent] = await Promise.all([
    callAuthenticatedBackend<Tenant>(
      `/admin/tenants/${encodeURIComponent(tenantId)}`,
    ),
    callAuthenticatedBackend<AgentEditorState | null>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/agent-instances/current`,
    ),
  ]);

  if (agent === null) {
    return (
      <section className="tenant-section">
        <header className="page-heading compact-heading">
          <p className="eyebrow">Agent Customer Service</p>
          <h2>Configure the agent</h2>
          <p>
            Create the first resumable Draft for this tenant. Capabilities,
            integrations and release gates are configured in their guided steps.
          </p>
        </header>
        {query.error ? (
          <p className="form-notice form-notice-error" role="alert">
            The Agent Draft could not be created.
          </p>
        ) : null}
        <form action={createCustomerServiceDraft} className="start-agent-card">
          <input type="hidden" name="tenantId" value={tenantId} />
          <input type="hidden" name="businessName" value={tenant.name} />
          <div>
            <h3>Agent Customer Service</h3>
            <p>
              Spanish and English presentation, with safe versioned
              configuration.
            </p>
          </div>
          <button type="submit">Create Agent Draft</button>
        </form>
      </section>
    );
  }

  return (
    <section className="tenant-section">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Agent Customer Service</p>
        <h2>Persona and languages</h2>
        <p>
          Configure business-facing presentation without exposing technical
          runtime, model or platform policy controls.
        </p>
      </header>
      {query.error === "stale" ? (
        <p className="form-notice form-notice-error" role="alert">
          Another administrator saved a newer Draft. The latest version is
          shown; review it before saving again.
        </p>
      ) : query.error ? (
        <p className="form-notice form-notice-error" role="alert">
          The change could not be saved.
        </p>
      ) : query.saved || query.created ? (
        <p className="form-notice form-notice-success" role="status">
          Saved as a new Agent Draft.
        </p>
      ) : null}
      <VersionBanner
        currentVersion={agent.editable_version.version_number}
        currentState={agent.editable_version.state}
        productionVersion={agent.production_version?.version_number ?? null}
      />
      <div className="agent-editor-grid">
        <PersonaForm tenantId={tenantId} agent={agent} />
        <LanguageForm tenantId={tenantId} agent={agent} />
      </div>
      <section
        className="quick-options-panel"
        aria-labelledby="quick-options-title"
      >
        <div>
          <p className="eyebrow">Derived preview</p>
          <h3 id="quick-options-title">Quick options</h3>
        </div>
        {agent.quick_options.length ? (
          <ul>
            {agent.quick_options.map((option) => (
              <li key={option}>{option}</li>
            ))}
          </ul>
        ) : (
          <p>
            Quick options will appear automatically when capabilities are
            enabled.
          </p>
        )}
      </section>
    </section>
  );
}
