import { configureApprovalRoute } from "../../app/actions";
import type { ApprovalRoute, CapabilityAction } from "../../lib/configuration";
import type { AgentEditorState } from "../../lib/tenant";

export function ApprovalRouteForm({
  tenantId,
  agent,
  actions,
  routes,
}: {
  tenantId: string;
  agent: AgentEditorState;
  actions: CapabilityAction[];
  routes: ApprovalRoute[];
}) {
  const required = actions.filter(
    (action) => action.risk === "HIGH" || action.requires_approval,
  );
  return (
    <section className="approval-route-section">
      <header className="page-heading compact-heading">
        <p className="eyebrow">Backoffice controls</p>
        <h2>High-risk approval routes</h2>
        <p>
          Each enabled high-risk action needs an authorized email route. Live
          Human Handoff is not a substitute.
        </p>
      </header>
      <div className="configuration-grid">
        {required.map((action) => {
          const route = routes.find(
            (candidate) => candidate.configuration.action === action.name,
          );
          return (
            <form
              action={configureApprovalRoute}
              className={`configuration-card approval-route-card ${route ? "route-complete" : "route-missing"}`}
              key={action.name}
            >
              <input type="hidden" name="tenantId" value={tenantId} />
              <input
                type="hidden"
                name="instanceId"
                value={agent.instance.id}
              />
              <input
                type="hidden"
                name="versionId"
                value={agent.editable_version.id}
              />
              <input
                type="hidden"
                name="routeRevision"
                value={route?.revision ?? 0}
              />
              <input
                type="hidden"
                name="capability"
                value={action.name.split(".")[0]}
              />
              <input type="hidden" name="action" value={action.name} />
              <header>
                <div>
                  <p className="eyebrow">HIGH · Approval required</p>
                  <h3>{action.name}</h3>
                </div>
                <span className={route ? "step-done" : "step-pending"}>
                  {route ? "Route complete" : "Missing route"}
                </span>
              </header>
              <label>
                Authorized approver emails
                <textarea
                  defaultValue={
                    route?.configuration.authorized_emails.join(", ") ?? ""
                  }
                  name="emails"
                  required
                  rows={3}
                />
              </label>
              <button type="submit">Save approval route</button>
            </form>
          );
        })}
      </div>
    </section>
  );
}
