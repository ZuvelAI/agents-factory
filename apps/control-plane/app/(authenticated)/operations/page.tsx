import { OperationsWorkspace } from "../../../components/operations/operations-workspace";
import { callAuthenticatedBackend } from "../../../lib/api";
import type { OperationsWorkspace as OperationsWorkspaceData } from "../../../lib/operations";
import type { Tenant } from "../../../lib/tenant";

export default async function OperationsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const query = await searchParams;
  const tenants = await callAuthenticatedBackend<Tenant[]>("/admin/tenants");
  const tenant =
    tenants.find((item) => item.id === query.tenant) ?? tenants.at(0) ?? null;
  if (!tenant) {
    return <p className="empty-state">Create a tenant before operating it.</p>;
  }
  const workspace = await callAuthenticatedBackend<OperationsWorkspaceData>(
    `/admin/tenants/${encodeURIComponent(tenant.id)}/operations/workspace`,
  );
  return (
    <section className="narrow-page operations-page">
      <header className="page-heading">
        <p className="eyebrow">Guided operations without routine SSH</p>
        <h1>Operations</h1>
        <p>
          Inspect recorded queue and connector health, handle dead-letter work
          with confirmation, and see later release dependencies fail closed.
        </p>
      </header>
      {query.saved ? (
        <p className="form-notice form-notice-success" role="status">
          Supported operational action completed and audited.
        </p>
      ) : query.error ? (
        <p className="form-notice form-notice-error" role="alert">
          The operational item changed or the action could not be completed.
        </p>
      ) : null}
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
        <button type="submit">Load operations</button>
      </form>
      <OperationsWorkspace tenantId={tenant.id} workspace={workspace} />
    </section>
  );
}
