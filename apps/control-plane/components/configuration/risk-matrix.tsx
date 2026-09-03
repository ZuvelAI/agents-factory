import { updateTenantPolicies } from "../../app/actions";
import type { CapabilityAction } from "../../lib/configuration";
import type { AgentEditorState } from "../../lib/tenant";

export function RiskMatrix({
  tenantId,
  agent,
  actions,
}: {
  tenantId: string;
  agent: AgentEditorState;
  actions: CapabilityAction[];
}) {
  const overrides = new Map(
    agent.editable_version.configuration.action_policies.map((item) => [
      item.action,
      item,
    ]),
  );
  return (
    <form action={updateTenantPolicies} className="matrix-form">
      <input type="hidden" name="tenantId" value={tenantId} />
      <input type="hidden" name="instanceId" value={agent.instance.id} />
      <input type="hidden" name="versionId" value={agent.editable_version.id} />
      <div className="table-scroll">
        <table className="data-table configuration-matrix">
          <caption>
            Platform minimums are locked. Administrators may only make a rule
            stricter.
          </caption>
          <thead>
            <tr>
              <th>Action</th>
              <th>Risk</th>
              <th>Identity</th>
              <th>Confirmation</th>
              <th>Approval</th>
            </tr>
          </thead>
          <tbody>
            {actions.map((action) => {
              const override = overrides.get(action.name);
              const confirmation =
                override?.confirmation_required ?? action.requires_confirmation;
              const approval =
                override?.approval_required ?? action.requires_approval;
              return (
                <tr key={action.name}>
                  <td>
                    <input
                      name="policyActions"
                      type="hidden"
                      value={action.name}
                    />
                    <code>{action.name}</code>
                  </td>
                  <td>{action.risk}</td>
                  <td>
                    <select
                      aria-label={`${action.name} identity level`}
                      defaultValue={
                        override?.identity_level ??
                        action.required_identity_level
                      }
                      name={`identity:${action.name}`}
                    >
                      {[0, 1, 2, 3].map((level) => (
                        <option
                          disabled={level < action.required_identity_level}
                          key={level}
                          value={level}
                        >
                          Level {level}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    {action.requires_confirmation ? (
                      <>
                        <input
                          name={`confirmation:${action.name}`}
                          type="hidden"
                          value="true"
                        />
                        <input
                          aria-label={`${action.name} confirmation required`}
                          checked
                          disabled
                          readOnly
                          type="checkbox"
                        />
                      </>
                    ) : (
                      <input
                        aria-label={`${action.name} confirmation required`}
                        defaultChecked={confirmation}
                        name={`confirmation:${action.name}`}
                        type="checkbox"
                        value="true"
                      />
                    )}
                  </td>
                  <td>
                    {action.requires_approval ? (
                      <>
                        <input
                          name={`approval:${action.name}`}
                          type="hidden"
                          value="true"
                        />
                        <input
                          aria-label={`${action.name} approval required`}
                          checked
                          disabled
                          readOnly
                          type="checkbox"
                        />
                      </>
                    ) : (
                      <input
                        aria-label={`${action.name} approval required`}
                        defaultChecked={approval}
                        name={`approval:${action.name}`}
                        type="checkbox"
                        value="true"
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="form-actions">
        <button type="submit">Save stricter policy as Draft</button>
      </div>
    </form>
  );
}
