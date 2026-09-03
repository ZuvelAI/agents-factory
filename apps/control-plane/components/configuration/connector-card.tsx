import Link from "next/link";

import {
  bindIntegrationOperations,
  checkIntegrationHealth,
  connectWooCommerce,
  reconnectIntegration,
  revokeIntegration,
  startIntegrationOAuth,
} from "../../app/actions";
import type { ConnectorCatalogEntry } from "../../lib/configuration";
import type { AgentEditorState } from "../../lib/tenant";

export function ConnectorCard({
  tenantId,
  agent,
  entry,
}: {
  tenantId: string;
  agent: AgentEditorState;
  entry: ConnectorCatalogEntry;
}) {
  const bindings = new Map(
    agent.editable_version.configuration.connector_bindings.map((binding) => [
      binding.binding_id,
      binding,
    ]),
  );
  return (
    <article className="configuration-card connector-card">
      <header>
        <div>
          <p className="eyebrow">{entry.auth_kind ?? "Planned"}</p>
          <h3>{entry.display_name}</h3>
        </div>
        <span className={entry.available ? "step-done" : "step-pending"}>
          {entry.availability === "AVAILABLE"
            ? "Available"
            : entry.availability === "SETUP_REQUIRED"
              ? "Deployment setup required"
              : "Coming later"}
        </span>
      </header>
      <p>{entry.note}</p>
      {entry.supported_operations.length ? (
        <p className="scope-summary">
          <strong>Supported operations:</strong>{" "}
          {entry.supported_operations.join(", ")}
        </p>
      ) : (
        <p className="operation-unavailable">No executable operations in v1.</p>
      )}

      {entry.connections.map((connection) => {
        const binding = bindings.get(connection.id);
        return (
          <section className="connection-panel" key={connection.id}>
            <div className="connection-heading">
              <span>
                <strong>{connection.status.replaceAll("_", " ")}</strong>
                <small>
                  Last check: {formatDate(connection.health.checked_at)}
                </small>
              </span>
              <span
                className={`health health-${connection.health.status.toLowerCase()}`}
              >
                {connection.health.status.replaceAll("_", " ")}
              </span>
            </div>
            <p className="scope-summary">
              <strong>Granted permissions:</strong>{" "}
              {connection.granted_scopes.join(", ") || "None reported"}
            </p>
            <div className="connection-actions">
              <ConnectionAction
                action={checkIntegrationHealth}
                connectionId={connection.id}
                label="Test health"
                tenantId={tenantId}
              />
              {connection.status === "REAUTH_REQUIRED" ? (
                <ConnectionAction
                  action={reconnectIntegration}
                  connectionId={connection.id}
                  label="Reconnect"
                  tenantId={tenantId}
                />
              ) : null}
              <ConnectionAction
                action={revokeIntegration}
                connectionId={connection.id}
                label="Revoke"
                secondary
                tenantId={tenantId}
              />
            </div>
            {connection.status === "CONNECTED" &&
            entry.supported_operations.length ? (
              <form action={bindIntegrationOperations} className="binding-form">
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
                  name="connectionId"
                  value={connection.id}
                />
                <input
                  type="hidden"
                  name="connectorName"
                  value={entry.connector_name}
                />
                <fieldset>
                  <legend>Agent operation mapping</legend>
                  {entry.supported_operations.map((operation) => (
                    <label key={operation}>
                      <input
                        defaultChecked={binding?.operations.includes(operation)}
                        name="operations"
                        type="checkbox"
                        value={operation}
                      />
                      {operation}
                    </label>
                  ))}
                </fieldset>
                <button type="submit">Save mapping as Draft</button>
              </form>
            ) : null}
          </section>
        );
      })}

      {entry.available && entry.connections.length === 0 ? (
        entry.connector_name === "meta_whatsapp" ? (
          <Link className="button-link" href={`/tenants/${tenantId}/whatsapp`}>
            Open WhatsApp setup
          </Link>
        ) : entry.auth_kind === "OAUTH2" ? (
          <form action={startIntegrationOAuth}>
            <input type="hidden" name="tenantId" value={tenantId} />
            <input
              type="hidden"
              name="connectorName"
              value={entry.connector_name}
            />
            {entry.required_scopes.map((scope) => (
              <input key={scope} type="hidden" name="scopes" value={scope} />
            ))}
            <button type="submit">Connect with OAuth</button>
          </form>
        ) : entry.connector_name === "woocommerce" ? (
          <form action={connectWooCommerce} className="credential-form">
            <input type="hidden" name="tenantId" value={tenantId} />
            <label>
              HTTPS store URL
              <input name="storeUrl" required type="url" />
            </label>
            <label>
              Consumer key
              <input
                autoComplete="off"
                name="consumerKey"
                required
                type="password"
              />
            </label>
            <label>
              Consumer secret
              <input
                autoComplete="off"
                name="consumerSecret"
                required
                type="password"
              />
            </label>
            <label>
              Permission
              <select name="permission">
                <option value="read">Read only</option>
                <option value="read_write">Read and write</option>
              </select>
            </label>
            <button type="submit">Connect WooCommerce</button>
          </form>
        ) : null
      ) : null}
    </article>
  );
}

function ConnectionAction({
  action,
  tenantId,
  connectionId,
  label,
  secondary = false,
}: {
  action: (data: FormData) => Promise<void>;
  tenantId: string;
  connectionId: string;
  label: string;
  secondary?: boolean;
}) {
  return (
    <form action={action}>
      <input type="hidden" name="tenantId" value={tenantId} />
      <input type="hidden" name="connectionId" value={connectionId} />
      <button
        className={secondary ? "secondary-button" : undefined}
        type="submit"
      >
        {label}
      </button>
    </form>
  );
}

function formatDate(value: string | null): string {
  return value
    ? new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeZone: "UTC",
      }).format(new Date(value))
    : "Never";
}
