import { CaseWorkspace } from "../../../../../components/cases/case-workspace";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import type {
  CasePriority,
  CaseWorkspace as CaseWorkspaceData,
} from "../../../../../lib/operations";

const priorities: CasePriority[] = ["LOW", "NORMAL", "HIGH", "CRITICAL"];

export default async function TenantCasesPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const { tenantId } = await params;
  const query = await searchParams;
  const priority = priorities.find((item) => item === query.priority) ?? null;
  const overdue = query.overdue === "true";
  const parameters = new URLSearchParams({
    overdue: String(overdue),
    page: query.page ?? "1",
    limit: "25",
  });
  if (priority) parameters.set("priority", priority);
  const workspace = await callAuthenticatedBackend<CaseWorkspaceData>(
    `/admin/tenants/${encodeURIComponent(tenantId)}/case-workspace?${parameters}`,
  );
  return (
    <section className="tenant-section cases-page">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Tenant operations</p>
        <h2>Cases</h2>
        <p>
          Review lifecycle, priority, targets, approval and human ownership.
        </p>
      </header>
      {query.saved === "resolved" ? (
        <p className="form-notice form-notice-success" role="status">
          Case resolved with a recorded event and customer result.
        </p>
      ) : null}
      <form className="operational-filters" method="GET">
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
      <CaseWorkspace
        destination="tenant"
        paginationQuery={parameters.toString()}
        tenantId={tenantId}
        workspace={workspace}
      />
    </section>
  );
}
