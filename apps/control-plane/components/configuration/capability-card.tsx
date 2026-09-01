import type { CapabilityManifest } from "../../lib/configuration";

function label(value: string): string {
  return value
    .split("_")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

export function CapabilityCard({
  manifest,
  enabled,
  boundOperations,
  editable = true,
}: {
  manifest: CapabilityManifest;
  enabled: boolean;
  boundOperations: ReadonlySet<string>;
  editable?: boolean;
}) {
  return (
    <article className="configuration-card capability-card">
      <header>
        <div>
          <p className="eyebrow">Capability Pack · v{manifest.version}</p>
          <h3>{label(manifest.stable_name)}</h3>
        </div>
        <label className="configuration-toggle">
          <input
            defaultChecked={enabled}
            disabled={!editable}
            name="capabilityNames"
            type="checkbox"
            value={manifest.stable_name}
          />
          {editable ? "Enabled in Draft" : "Shared registry"}
        </label>
      </header>
      <p>{manifest.intents.map(label).join(" · ")}</p>
      <ul className="operation-list">
        {manifest.actions.map((action) => {
          const required = action.required_connector_operations;
          const available =
            action.connector_requirement_mode === "none" ||
            required.every((operation) => boundOperations.has(operation));
          return (
            <li key={action.name}>
              <span>
                <strong>
                  {label(action.name.split(".")[1] ?? action.name)}
                </strong>
                <small>{action.description}</small>
              </span>
              <span
                className={
                  available ? "operation-ready" : "operation-unavailable"
                }
              >
                {available ? "Mapped" : "Needs connector mapping"}
              </span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}
