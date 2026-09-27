"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { beginWhatsAppSignup, finishWhatsAppSignup } from "../../../../actions";
import {
  signupBlockReason,
  type WhatsAppMode,
} from "../../../../../lib/whatsapp-mode";
import { loadMetaSdk } from "../../../../../lib/meta-sdk-loader";
import { runSignupSession } from "../../../../../lib/whatsapp-signup-session";

export function EmbeddedSignup({ tenantId }: { tenantId: string }) {
  const router = useRouter();
  const [status, setStatus] = useState<"idle" | "working" | "error">("idle");
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<WhatsAppMode | null>(null);
  const [confirmedExclusive, setConfirmedExclusive] = useState(false);
  const blocked = signupBlockReason(mode, confirmedExclusive);
  const activeAttempt = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      activeAttempt.current?.abort();
    },
    [],
  );

  async function connect() {
    if (blocked || !mode || activeAttempt.current) return;
    const attempt = new AbortController();
    activeAttempt.current = attempt;
    setStatus("working");
    setMessage("Opening Meta Embedded Signup…");
    try {
      const started = await beginWhatsAppSignup(tenantId, mode);
      if (attempt.signal.aborted) return;
      if (!started.ok) throw new Error(started.message);
      const sdk = await loadMetaSdk(started.data.app_id, attempt.signal);
      const { code, assets } = await runSignupSession(
        sdk,
        window,
        started.data.configuration_id,
        mode,
        attempt.signal,
      );
      if (attempt.signal.aborted) return;
      const finished = await finishWhatsAppSignup({
        tenantId,
        state: started.data.state,
        code,
        businessId: assets.businessId,
        wabaId: assets.wabaId,
        phoneNumberId: assets.phoneNumberId,
        mode,
      });
      if (attempt.signal.aborted) return;
      if (!finished.ok) throw new Error(finished.message);
      setStatus("idle");
      setMessage("WhatsApp connected.");
      router.refresh();
    } catch (error) {
      if (attempt.signal.aborted) return;
      setStatus("error");
      setMessage(
        error instanceof Error
          ? error.message
          : "The WhatsApp connection could not be completed.",
      );
    } finally {
      if (activeAttempt.current === attempt) activeAttempt.current = null;
    }
  }

  return (
    <div className="signup-action">
      <fieldset disabled={status === "working"}>
        <legend>¿Cómo quieres usar este número?</legend>
        <label>
          <input
            type="radio"
            name="whatsapp-mode"
            checked={mode === "API_ONLY"}
            onChange={() => {
              setMode("API_ONLY");
              setConfirmedExclusive(false);
              setMessage("");
            }}
          />
          Número exclusivo para el agente
        </label>
        <p>
          Usa un número separado. Esta opción no conserva WhatsApp Business en
          el celular con ese mismo número.
        </p>
        <label>
          <input
            type="radio"
            name="whatsapp-mode"
            checked={mode === "COEXISTENCE"}
            onChange={() => {
              setMode("COEXISTENCE");
              setConfirmedExclusive(false);
              setMessage("");
            }}
          />
          Conservar WhatsApp Business + agente — pendiente de habilitación
        </label>
        <p>
          Para un número ya activo en WhatsApp Business. Su conexión dependerá
          de Meta; no se convertirá automáticamente en un número exclusivo.
        </p>
        {mode === "API_ONLY" && (
          <label>
            <input
              type="checkbox"
              checked={confirmedExclusive}
              onChange={(event) => setConfirmedExclusive(event.target.checked)}
            />
            Confirmo que este número será exclusivo para la API, no para la
            aplicación del celular.
          </label>
        )}
      </fieldset>
      {blocked && <p role="status">{blocked}</p>}
      <button
        type="button"
        onClick={connect}
        disabled={status === "working" || blocked !== null}
      >
        {status === "working" ? "Connecting…" : "Connect with Meta"}
      </button>
      {message ? (
        <p role={status === "error" ? "alert" : "status"}>{message}</p>
      ) : null}
    </div>
  );
}
