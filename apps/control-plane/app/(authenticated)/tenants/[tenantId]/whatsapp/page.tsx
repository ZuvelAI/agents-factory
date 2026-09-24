import {
  refreshWhatsAppHealth,
  revokeWhatsAppAccount,
} from "../../../../actions";
import { callAuthenticatedBackend } from "../../../../../lib/api";
import { EmbeddedSignup } from "./embedded-signup";
import { TestMessage } from "./test-message";

type WhatsAppAccount = {
  id: string;
  business_id: string | null;
  waba_id: string;
  phone_number_id: string;
  status: string;
  mode: "API_ONLY" | "COEXISTENCE";
  coexistence_eligibility: "ELIGIBLE" | "INELIGIBLE" | "UNKNOWN";
  granted_scopes: string[];
  health_status: "HEALTHY" | "REAUTH_REQUIRED" | "ERROR" | "UNKNOWN";
  last_health_checked_at: string | null;
  token_expires_at: string | null;
  verified_at: string | null;
};

export default async function WhatsAppSetupPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  let accounts: WhatsAppAccount[] = [];
  let backendAvailable = true;
  try {
    accounts = await callAuthenticatedBackend<WhatsAppAccount[]>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp`,
    );
  } catch {
    backendAvailable = false;
  }

  return (
    <section className="whatsapp-setup" aria-labelledby="whatsapp-title">
      <p className="eyebrow">Milestone 2</p>
      <h1 id="whatsapp-title">WhatsApp setup</h1>
      <p className="setup-intro">
        Meta Embedded Signup authorizes the client&apos;s own business and
        number. AI Workers never asks for or displays access tokens.
      </p>

      <div className="setup-panel">
        <div>
          <h2>Connection</h2>
          <p>
            Elige entre un número exclusivo o conservar la aplicación del celular.
            La coexistencia está pendiente de habilitación y validación; elegirla no conecta ni migra tu número.
          </p>
        </div>
        <EmbeddedSignup tenantId={tenantId} />
      </div>

      {!backendAvailable ? (
        <p className="connection-notice" role="status">
          Not connected — the local backend is unavailable.
        </p>
      ) : null}

      <div className="account-grid">
        {accounts.map((account) => (
          <article className="account-card" key={account.id}>
            <div className="account-card-heading">
              <h2>{account.phone_number_id}</h2>
              <span
                className={`health health-${account.health_status.toLowerCase()}`}
              >
                {account.health_status.replaceAll("_", " ")}
              </span>
            </div>
            <dl>
              <div>
                <dt>Mode</dt>
                <dd>{account.mode.replace("_", " ")}</dd>
              </div>
              <div>
                <dt>Coexistence</dt>
                <dd>{account.coexistence_eligibility}</dd>
              </div>
              <div>
                <dt>Business</dt>
                <dd>{account.business_id ?? "Legacy mapping"}</dd>
              </div>
              <div>
                <dt>WABA</dt>
                <dd>{account.waba_id}</dd>
              </div>
              <div>
                <dt>Scopes</dt>
                <dd>{account.granted_scopes.join(", ")}</dd>
              </div>
              <div>
                <dt>Last check</dt>
                <dd>{formatDate(account.last_health_checked_at)}</dd>
              </div>
            </dl>
            <div className="account-actions">
              <form action={refreshWhatsAppHealth}>
                <input type="hidden" name="tenantId" value={tenantId} />
                <input type="hidden" name="accountId" value={account.id} />
                <button type="submit">Check health</button>
              </form>
              <form action={revokeWhatsAppAccount}>
                <input type="hidden" name="tenantId" value={tenantId} />
                <input type="hidden" name="accountId" value={account.id} />
                <button className="secondary-button" type="submit">
                  Revoke
                </button>
              </form>
            </div>
            {account.status === "active" && (
              <TestMessage tenantId={tenantId} accountId={account.id} />
            )}
          </article>
        ))}
      </div>
      {backendAvailable && accounts.length === 0 ? (
        <p className="connection-notice" role="status">
          Conecta la cuenta de WhatsApp de este cliente para habilitar el envío
          de prueba.
        </p>
      ) : null}
    </section>
  );
}

function formatDate(value: string | null): string {
  if (!value) return "Never";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}
