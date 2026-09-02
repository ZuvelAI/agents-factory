import { CaseWorkspace } from "../../../components/cases/case-workspace";
import { callAuthenticatedBackend } from "../../../lib/api";
import type {
  CasePriority,
  CaseWorkspace as CaseWorkspaceData,
} from "../../../lib/operations";
import type { Tenant } from "../../../lib/tenant";

const priorities: CasePriority[] = ["LOW", "NORMAL", "HIGH", "CRITICAL"];

export default async function CasesPage({
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
      <p className="empty-state">Create a tenant before reviewing cases.</p>
    );
  }
  const priority = priorities.find((item) => item === query.priority) ?? null;
  const overdue = query.overdue === "true";
  const page = positivePage(query.page);
  const parameters = new URLSearchParams({
    overdue: String(overdue),
    page: String(page),
    limit: "25",
  });
  if (priority) parameters.set("priority", priority);
  const paginationParameters = new URLSearchParams(parameters);
  paginationParameters.set("tenant", tenant.id);
  const workspace = await callAuthenticatedBackend<CaseWorkspaceData>(
    `/admin/tenants/${encodeURIComponent(tenant.id)}/case-workspace?${parameters}`,
  );

  return (
    <section className="narrow-page cases-page">
      <header className="page-heading">
        <p className="eyebrow">Human-owned service work</p>
        <h1>Cases</h1>
        <p>
          Filter business cases by priority and target, inspect approval and
          reviewer evidence, and record supported outcomes.
        </p>
      </header>
      {query.saved === "resolved" ? (
        <p className="form-notice form-notice-success" role="status">
          Case resolved with a recorded event and customer result.
        </p>
      ) : query.error ? (
        <p className="form-notice form-notice-error" role="alert">
          The case changed or could not be resolved. Reload and review it.
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
        <label>
          Priority
          <select defaultValue={priority ?? ""} name="priority">
            <option value="">All priorities</option>
            {priorities.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="confirmation-field">
          <input
            defaultChecked={overdue}
            name="overdue"
            type="checkbox"
            value="true"
          />
          Overdue only
        </label>
        <button type="submit">Apply case filters</button>
      </form>
      <p className="data-freshness">
        Generated{" "}
        {new Date(workspace.generated_at).toLocaleString("en-US", {
          timeZone: "UTC",
        })}
        . Results are tenant-isolated and paginated.
      </p>
      <CaseWorkspace
        paginationQuery={paginationParameters.toString()}
        tenantId={tenant.id}
        workspace={workspace}
      />
    </section>
  );
}

function positivePage(value: string | undefined): number {
  const page = Number(value ?? "1");
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}
