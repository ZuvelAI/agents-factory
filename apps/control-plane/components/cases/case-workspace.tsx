import Link from "next/link";

import { resolveOperationalCase } from "../../app/actions";
import { formatTime } from "../../lib/dashboard";
import type { CaseWorkspace as CaseWorkspaceData } from "../../lib/operations";

export function CaseWorkspace({
  tenantId,
  workspace,
  destination = "global",
  paginationQuery = "",
}: {
  tenantId: string;
  workspace: CaseWorkspaceData;
  destination?: "global" | "tenant";
  paginationQuery?: string;
}) {
  if (workspace.cases.length === 0) {
    return (
      <section className="empty-state operational-empty">
        <h2>No cases match these filters</h2>
        <p>Change the priority, target or page to inspect other work.</p>
      </section>
    );
  }

  return (
    <div className="case-list">
      {workspace.cases.map((item) => (
        <article className="case-card" key={item.id}>
          <header>
            <div>
              <p className="eyebrow">{item.capability}</p>
              <h2>{humanize(item.issue_type)}</h2>
            </div>
            <div className="status-stack">
              <span
                className={`review-state review-${item.priority.toLowerCase()}`}
              >
                {item.priority}
              </span>
              <span
                className={`review-state review-${item.target_status.toLowerCase()}`}
              >
                {humanize(item.target_status)}
              </span>
            </div>
          </header>
          <dl className="case-facts">
            <div>
              <dt>Lifecycle</dt>
              <dd>{humanize(item.status)}</dd>
            </div>
            <div>
              <dt>Target</dt>
              <dd>{formatTime(item.target_at)}</dd>
            </div>
            <div>
              <dt>Reviewer</dt>
              <dd>{item.reviewer_reference}</dd>
            </div>
            <div>
              <dt>Approval</dt>
              <dd>{humanize(item.approval_status)}</dd>
            </div>
          </dl>
          <p className="trace-reference">
            Case <code>{item.id}</code> · revision {item.revision}
          </p>
          {item.latest_event ? (
            <p>
              Latest event: <strong>{humanize(item.latest_event)}</strong>
              {item.latest_reason ? ` · ${item.latest_reason}` : null}
            </p>
          ) : null}
          {item.status === "IN_PROGRESS" ? (
            <details className="operational-action">
              <summary>Resolve this case</summary>
              <form action={resolveOperationalCase}>
                <input type="hidden" name="tenantId" value={tenantId} />
                <input type="hidden" name="caseId" value={item.id} />
                <input type="hidden" name="revision" value={item.revision} />
                <input type="hidden" name="destination" value={destination} />
                <label>
                  Internal resolution reason
                  <textarea name="reason" maxLength={1000} required rows={2} />
                </label>
                <label>
                  Customer-visible result
                  <textarea
                    name="customerResult"
                    maxLength={4000}
                    required
                    rows={2}
                  />
                </label>
                <button type="submit">Resolve case</button>
              </form>
            </details>
          ) : null}
        </article>
      ))}
      <nav aria-label="Case pages" className="operational-pagination">
        {workspace.page > 1 ? (
          <Link href={pageLink(paginationQuery, workspace.page - 1)}>
            Previous page
          </Link>
        ) : (
          <span />
        )}
        <span>
          Page {workspace.page} · {workspace.total} cases
        </span>
        {workspace.has_more ? (
          <Link href={pageLink(paginationQuery, workspace.page + 1)}>
            Next page
          </Link>
        ) : null}
      </nav>
    </div>
  );
}

function pageLink(query: string, page: number): string {
  const parameters = new URLSearchParams(query);
  parameters.set("page", String(page));
  return `?${parameters}`;
}

function humanize(value: string): string {
  return value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}
