import { EvalDrafts } from "../../../components/evals/eval-drafts";
import { callAuthenticatedBackend } from "../../../lib/api";
import type { ConversationWorkspace } from "../../../lib/conversations";
import type { OperationsWorkspace } from "../../../lib/operations";
import type { Tenant } from "../../../lib/tenant";

export default async function EvalsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const query = await searchParams;
  const tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  const tenant =
    tenants.find((item) => item.id === query.tenant) ?? tenants.at(0) ?? null;
  if (!tenant) {
    return (
      <p className="empty-state">Create a tenant before reviewing evals.</p>
    );
  }
  const [conversations, operations] = await Promise.all([
    callAuthenticatedBackend<ConversationWorkspace>(
      `/admin/tenants/${encodeURIComponent(tenant.id)}/conversations/review-workspace`,
    ),
    callAuthenticatedBackend<OperationsWorkspace>(
      `/admin/tenants/${encodeURIComponent(tenant.id)}/operations/workspace?limit=1`,
    ),
  ]);
  return (
    <section className="narrow-page evals-page">
      <header className="page-heading">
        <p className="eyebrow">Regression review boundary</p>
        <h1>Evals</h1>
        <p>
          Inspect anonymized Draft candidates and the latest exact-version
          Production Quality Gate decision.
        </p>
      </header>
      <form className="operational-filters" method="GET">
        <label>
          Tenant
          <select defaultValue={tenant.id} name="tenant">
            {tenants.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Load Eval Drafts</button>
      </form>
      <EvalDrafts
        drafts={conversations.eval_drafts}
        qualityGate={operations.quality_gate}
        tenantId={tenant.id}
      />
    </section>
  );
}
