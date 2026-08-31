"use client";

import type { FormEvent } from "react";
import {
  ACTION_LABELS,
  APPROVAL_REASONS,
  type ReviewDetails,
} from "../../lib/approval-contract";

export type DecisionFields = {
  decision: string;
  reason_code: string;
  explanation: string;
  confirmed: boolean;
};

export function DecisionForm({
  details,
  busy,
  onDecision,
}: {
  details: ReviewDetails;
  busy: boolean;
  onDecision: (fields: DecisionFields) => void;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    onDecision({
      decision: String(data.get("decision")),
      reason_code: String(data.get("reason")),
      explanation: String(data.get("explanation")),
      confirmed: data.get("confirmed") === "on",
    });
  }
  return (
    <form className="approval-form" autoComplete="off" onSubmit={submit}>
      <h2>3. Revisa y decide</h2>
      <dl className="approval-details">
        <div>
          <dt>Operación solicitada</dt>
          <dd>
            {ACTION_LABELS[details.action] ?? "Revisión de una operación"}
          </dd>
        </div>
        {details.resource_reference ? (
          <div>
            <dt>Referencia</dt>
            <dd>{details.resource_reference}</dd>
          </div>
        ) : null}
        <div>
          <dt>Solicitud</dt>
          <dd>{details.request_id}</dd>
        </div>
        <div>
          <dt>Verificación válida hasta</dt>
          <dd>
            <time dateTime={details.expires_at}>
              {new Date(details.expires_at).toLocaleString("es-CO")}
            </time>
          </dd>
        </div>
      </dl>
      <p className="approval-notice">
        Aprobar autoriza la revisión final del backend. No confirma que la
        operación ya se haya realizado.
      </p>
      <fieldset disabled={busy}>
        <legend>Tu decisión</legend>
        <label className="approval-choice">
          <input type="radio" name="decision" value="APPROVE" required />{" "}
          Aprobar solicitud
        </label>
        <label className="approval-choice">
          <input type="radio" name="decision" value="REJECT" required />{" "}
          Rechazar solicitud
        </label>
        <label htmlFor="approval-reason">Motivo</label>
        <select id="approval-reason" name="reason" defaultValue="" required>
          <option value="" disabled>
            Selecciona un motivo
          </option>
          {Object.entries(APPROVAL_REASONS)
            .filter(
              ([key]) =>
                !key.startsWith("order_") ||
                details.action.startsWith("orders."),
            )
            .filter(
              ([key]) =>
                !key.startsWith("appointment_") ||
                details.action.startsWith("appointments."),
            )
            .map(([key, label]) => (
              <option value={key} key={key}>
                {label}
              </option>
            ))}
        </select>
        <label htmlFor="approval-explanation">
          Explicación para el registro interno
        </label>
        <textarea
          id="approval-explanation"
          name="explanation"
          maxLength={2000}
          required
          rows={3}
          aria-describedby="explanation-help"
        />
        <p id="explanation-help">
          No incluyas contraseñas, códigos ni datos sensibles. El cliente
          recibirá un resultado estructurado, no esta nota.
        </p>
        <label className="approval-choice">
          <input name="confirmed" type="checkbox" required /> Confirmo que
          revisé la solicitud y deseo registrar esta decisión.
        </label>
        <button type="submit">
          {busy ? "Registrando…" : "Confirmar decisión"}
        </button>
      </fieldset>
    </form>
  );
}
