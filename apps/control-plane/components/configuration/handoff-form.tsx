import { configureHandoff } from "../../app/actions";
import type {
  HandoffConfiguration,
  HumanSurfaceOption,
  WhatsAppAccount,
} from "../../lib/configuration";
import type { AgentEditorState, Tenant } from "../../lib/tenant";

export function HandoffForm({
  tenant,
  agent,
  accounts,
  configurations,
  surfaces,
}: {
  tenant: Tenant;
  agent: AgentEditorState;
  accounts: WhatsAppAccount[];
  configurations: HandoffConfiguration[];
  surfaces: HumanSurfaceOption[];
}) {
  const coexistenceSurface = surfaces.find(
    (option) => option.surface === "WHATSAPP_COEXISTENCE",
  );
  const eligible = accounts.find(
    (account) =>
      coexistenceSurface !== undefined &&
      account.status === "active" &&
      account.mode === "COEXISTENCE" &&
      account.coexistence_eligibility === "ELIGIBLE" &&
      account.health_status === "HEALTHY" &&
      account.verified_at !== null,
  );
  const current = eligible
    ? configurations.find((item) => item.account_id === eligible.id)
    : undefined;
  const enabled = current?.configuration.enabled ?? false;
  return (
    <section className="configuration-card handoff-card">
      <header>
        <div>
          <p className="eyebrow">Human Operations</p>
          <h3>Live Human Handoff</h3>
        </div>
        <span className={eligible ? "step-done" : "step-pending"}>
          {eligible ? "Surface verified" : "No verified surface"}
        </span>
      </header>
      <p>
        Handoff is separate from backoffice approvals. API-only WhatsApp cannot
        offer live human chat.
      </p>
      {eligible ? (
        <form action={configureHandoff} className="configuration-form">
          <input type="hidden" name="tenantId" value={tenant.id} />
          <input type="hidden" name="instanceId" value={agent.instance.id} />
          <input
            type="hidden"
            name="versionId"
            value={agent.editable_version.id}
          />
          <input type="hidden" name="accountId" value={eligible.id} />
          <input
            type="hidden"
            name="surfaceAdapter"
            value={coexistenceSurface?.adapter}
          />
          <input type="hidden" name="revision" value={current?.revision ?? 0} />
          <label className="configuration-toggle">
            <input
              defaultChecked={enabled}
              name="enabled"
              type="checkbox"
              value="true"
            />
            Enable Live Human Handoff
          </label>
          <div className="form-grid">
            <label>
              Inactivity close window
              <input
                defaultValue={current?.configuration.inactivity_hours ?? 12}
                max={168}
                min={1}
                name="inactivityHours"
                type="number"
              />
            </label>
            <label>
              Timezone
              <input
                defaultValue={
                  current?.configuration.timezone ?? tenant.timezone ?? "UTC"
                }
                name="timezone"
                required
              />
            </label>
          </div>
          <div className="form-actions">
            <button type="submit">Save handoff configuration</button>
          </div>
        </form>
      ) : (
        <label className="configuration-toggle configuration-toggle-disabled">
          <input disabled type="checkbox" />
          Enable Live Human Handoff
          <small>
            Requires a verified Coexistence or supported external inbox surface.
          </small>
        </label>
      )}
    </section>
  );
}
