"use client";

import type { FormEvent } from "react";

export function OTPForm({
  stage,
  busy,
  onEmail,
  onCode,
  onResend,
}: {
  stage: "EMAIL" | "OTP";
  busy: boolean;
  onEmail: (email: string) => void;
  onCode: (code: string) => void;
  onResend: () => void;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = new FormData(form).get(stage === "EMAIL" ? "email" : "code");
    if (typeof input !== "string") return;
    form.reset();
    if (stage === "EMAIL") onEmail(input);
    else onCode(input);
  }
  return (
    <form className="approval-form" autoComplete="off" onSubmit={submit}>
      <fieldset disabled={busy}>
        <legend>
          {stage === "EMAIL"
            ? "1. Confirma tu correo"
            : "2. Verifica el código"}
        </legend>
        {stage === "EMAIL" ? (
          <>
            <label htmlFor="approval-email">Correo autorizado</label>
            <input
              id="approval-email"
              name="email"
              type="email"
              autoComplete="off"
              maxLength={254}
              required
              aria-describedby="email-help"
            />
            <p id="email-help">
              Usa el correo que recibió el enlace. Si está autorizado, recibirá
              un código por separado.
            </p>
          </>
        ) : (
          <>
            <label htmlFor="approval-code">Código de verificación</label>
            <input
              id="approval-code"
              name="code"
              type="password"
              inputMode="numeric"
              autoComplete="off"
              pattern="[0-9]{6}"
              minLength={6}
              maxLength={6}
              required
              aria-describedby="code-help"
            />
            <p id="code-help">
              Introduce los 6 dígitos del correo. El código vence; los intentos
              son limitados.
            </p>
          </>
        )}
        <button type="submit">
          {busy
            ? "Verificando…"
            : stage === "EMAIL"
              ? "Enviar código"
              : "Verificar y revisar"}
        </button>
        {stage === "OTP" ? (
          <button type="button" className="secondary-button" onClick={onResend}>
            Solicitar otro código
          </button>
        ) : null}
      </fieldset>
    </form>
  );
}
