"use client";

import { useState } from "react";
import { publishAgentCandidate } from "./agent-publication-actions";

export function PublishAccountForm({
  tenantId,
  revision,
  runId,
  versionId,
  accounts,
  bindings,
}: {
  tenantId: string;
  revision: number;
  runId: string;
  versionId: string;
  accounts: {
    id: string;
    display_phone_number: string | null;
    status: string;
    health_status: string;
  }[];
  bindings: { whatsapp_account_id: string; revision: number }[];
}) {
  const [accountId, setAccountId] = useState("");
  const bindingRevision =
    bindings.find((b) => b.whatsapp_account_id === accountId)?.revision ?? 0;
  return (
    <form action={publishAgentCandidate}>
      <input type="hidden" name="tenantId" value={tenantId} />
      <input type="hidden" name="expectedRevision" value={revision} />
      <input type="hidden" name="runId" value={runId} />
      <input type="hidden" name="versionId" value={versionId} />
      <input
        type="hidden"
        name="expectedBindingRevision"
        value={bindingRevision}
      />
      <label>
        Elige la cuenta de WhatsApp
        <select
          name="accountId"
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          required
        >
          <option value="">Elige la cuenta de WhatsApp</option>
          {accounts.map((a) => (
            <option
              key={a.id}
              disabled={a.status !== "active" || a.health_status !== "HEALTHY"}
              value={a.id}
            >
              {a.display_phone_number ?? a.id} · {a.health_status}
            </option>
          ))}
        </select>
      </label>
      <label>
        <input name="confirmPublish" type="checkbox" required />
        Confirmo publicar esta versión revisada en la cuenta seleccionada.
      </label>
      <button type="submit" disabled={!accountId}>
        Publicar versión en WhatsApp
      </button>
    </form>
  );
}
