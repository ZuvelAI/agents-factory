import {
  checkOperationalIntegration,
  mutateDeadLetter,
  reconnectOperationalIntegration,
} from "../../app/actions";
import { formatTime } from "../../lib/dashboard";
import type { OperationsWorkspace as OperationsWorkspaceData } from "../../lib/operations";

export function OperationsWorkspace({
  tenantId,
  workspace,
}: {
  tenantId: string;
  workspace: OperationsWorkspaceData;
}) {
  return (
    <div className="operations-workspace">
      <p className="data-freshness">
        Generated {formatTime(workspace.generated_at)} · state {workspace.state}
        . Worker state is based on recorded queue facts, not an unavailable
        heartbeat claim.
      </p>
      <section className="operational-section">
        <header>
          <p className="eyebrow">Queue and workers</p>
          <h2>Recorded workload by topic</h2>
        </header>
        <div className="operational-grid">
          {workspace.topics.map((topic) => (
            <article className="operational-card" key={topic.topic}>
              <span
                className={`review-state review-${topic.state.toLowerCase()}`}
              >
                {topic.state}
              </span>
              <h3>{humanize(topic.topic)}</h3>
              <dl className="case-facts">
                <div>
                  <dt>Pending</dt>
                  <dd>{topic.pending}</dd>
                </div>
                <div>
                  <dt>Processing</dt>
                  <dd>{topic.processing}</dd>
                </div>
                <div>
                  <dt>Failed</dt>
                  <dd>{topic.failed}</dd>
                </div>
                <div>
                  <dt>Dead letter</dt>
                  <dd>{topic.dead_letter}</dd>
                </div>
              </dl>
              <small>
                Oldest ready work: {formatTime(topic.oldest_pending_at)}
              </small>
            </article>
          ))}
        </div>
      </section>

      <section className="operational-section">
        <header>
          <p className="eyebrow">Tenant connections</p>
          <h2>Integration health</h2>
        </header>
        <div className="operational-grid integration-operations">
          {workspace.integrations.map((connection) => (
            <article className="operational-card" key={connection.id}>
              <span
                className={`review-state review-${connection.health_status.toLowerCase()}`}
              >
                {humanize(connection.health_status)}
              </span>
              <h3>{humanize(connection.connector_name)}</h3>
              <p>{humanize(connection.connection_status)}</p>
              <p>
                Last check: {formatTime(connection.last_health_checked_at)}
                {connection.last_error_code
                  ? ` · ${humanize(connection.last_error_code)}`
                  : null}
              </p>
              <div className="operational-card-actions">
                <form action={checkOperationalIntegration}>
                  <input type="hidden" name="tenantId" value={tenantId} />
                  <input
                    type="hidden"
                    name="connectionId"
                    value={connection.id}
                  />
                  <button type="submit">Check health</button>
                </form>
                <form action={reconnectOperationalIntegration}>
                  <input type="hidden" name="tenantId" value={tenantId} />
                  <input
                    type="hidden"
                    name="connectionId"
                    value={connection.id}
                  />
                  <button className="secondary-button" type="submit">
                    Reconnect
                  </button>
                </form>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="operational-section">
        <header>
          <p className="eyebrow">Manual intervention</p>
          <h2>Dead-letter work</h2>
          <p>Payloads and credentials are intentionally not exposed here.</p>
        </header>
        <div className="dlq-list">
          {workspace.dead_letters.map((item) => (
            <article className="dlq-card" key={item.id}>
              <header>
                <div>
                  <h3>{humanize(item.topic)}</h3>
                  <p>{humanize(item.reason_code)}</p>
                </div>
                <span className={`review-state review-${item.status}`}>
                  {item.status}
                </span>
              </header>
              <p>
                Attempts {item.attempt_count}/{item.max_attempts} · DLQ{" "}
                <code>{item.id}</code>
              </p>
              {item.status === "open" ? (
                <div className="dlq-actions">
                  {(["RETRY", "DISCARD", "RESOLVE"] as const).map((action) => (
                    <details key={action}>
                      <summary>{humanize(action)}</summary>
                      <form action={mutateDeadLetter}>
                        <input type="hidden" name="tenantId" value={tenantId} />
                        <input
                          type="hidden"
                          name="deadLetterId"
                          value={item.id}
                        />
                        <input type="hidden" name="dlqAction" value={action} />
                        <label>
                          Operational reason
                          <textarea
                            name="reason"
                            required
                            maxLength={500}
                            rows={2}
                          />
                        </label>
                        <label className="confirmation-field">
                          <input
                            name="confirmation"
                            required
                            type="checkbox"
                            value="true"
                          />
                          I reviewed this job and confirm {action.toLowerCase()}
                          .
                        </label>
                        <button type="submit">
                          Confirm {action.toLowerCase()}
                        </button>
                      </form>
                    </details>
                  ))}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      </section>

      <section className="operational-section">
        <header>
          <p className="eyebrow">Audit trail</p>
          <h2>Recent supported mutations</h2>
        </header>
        <ol className="audit-list">
          {workspace.recent_audit.map((event) => (
            <li key={`${event.correlation_id}-${event.event_type}`}>
              <strong>{humanize(event.event_type)}</strong>
              <span>{formatTime(event.occurred_at)}</span>
              <code>{event.correlation_id}</code>
            </li>
          ))}
        </ol>
      </section>

      <section className="operational-section">
        <header>
          <p className="eyebrow">Health and incident evidence</p>
          <h2>Operational detection</h2>
        </header>
        <div className="operational-grid">
          <article className="operational-card">
            <span
              className={`review-state review-${workspace.health.state.toLowerCase()}`}
            >
              {humanize(workspace.health.state)}
            </span>
            <h3>Tenant health</h3>
            <p>
              {workspace.health.components.length} component signals recorded.
            </p>
          </article>
          {workspace.incidents.map((incident) => (
            <article className="operational-card" key={incident.id}>
              <span
                className={`review-state review-${incident.severity.toLowerCase()}`}
              >
                {humanize(incident.severity)}
              </span>
              <h3>{incident.title}</h3>
              <p>{incident.occurrence_count} correlated occurrence(s).</p>
              <code>{incident.correlation_id}</code>
            </article>
          ))}
        </div>
      </section>

      <section className="operational-section">
        <header>
          <p className="eyebrow">Release controls</p>
          <h2>Fail-closed controls</h2>
        </header>
        <div className="operational-grid unavailable-grid">
          <QualityGateCard gate={workspace.quality_gate} />
          <article className="operational-card">
            <span className="review-state review-healthy">Workflow ready</span>
            <h3>Deployments</h3>
            {workspace.deployments.latest.length ? (
              workspace.deployments.latest.map((deployment) => (
                <p key={deployment.id}>
                  {deployment.environment}: {humanize(deployment.status)} ·{" "}
                  <code>{deployment.release_version}</code>
                </p>
              ))
            ) : (
              <p>No deployment has been recorded for this tenant.</p>
            )}
            <small>Production requires GitHub environment approval.</small>
          </article>
        </div>
      </section>
    </div>
  );
}

function QualityGateCard({
  gate,
}: {
  gate: OperationsWorkspaceData["quality_gate"];
}) {
  const latest = gate.latest;
  return (
    <article className="operational-card">
      <span
        className={`review-state review-${latest?.passed ? "healthy" : "unavailable"}`}
      >
        {latest?.passed ? "Passed" : "Blocked"}
      </span>
      <h3>Production Quality Gate</h3>
      {latest ? (
        <>
          <p>
            {latest.passed_cases} passed · {latest.failed_cases} failed · exact
            version evidence required.
          </p>
          <code>{latest.id}</code>
        </>
      ) : (
        <p>No persisted exact-version decision exists yet.</p>
      )}
    </article>
  );
}

function humanize(value: string): string {
  return value
    .toLowerCase()
    .replaceAll(/[._]/g, " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}
