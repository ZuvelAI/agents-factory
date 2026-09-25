"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { beginWhatsAppSignup, finishWhatsAppSignup } from "../../../../actions";
import {
  signupBlockReason,
  type WhatsAppMode,
} from "../../../../../lib/whatsapp-mode";
import { runSignupSession } from "../../../../../lib/whatsapp-signup-session";

type MetaLoginResponse = { authResponse?: { code?: string } };
type MetaSdk = {
  init(options: {
    appId: string;
    cookie: boolean;
    xfbml: boolean;
    version: string;
  }): void;
  login(
    callback: (response: MetaLoginResponse) => void,
    options: Record<string, unknown>,
  ): void;
};

declare global {
  interface Window {
    FB?: MetaSdk;
  }
}

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
      const sdk = await loadMetaSdk(started.data.app_id);
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

async function loadMetaSdk(appId: string): Promise<MetaSdk> {
  if (!window.FB) {
    await new Promise<void>((resolve, reject) => {
      const existing = document.getElementById("facebook-jssdk");
      if (existing) {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener(
          "error",
          () => reject(new Error("Meta SDK failed to load")),
          {
            once: true,
          },
        );
        return;
      }
      const script = document.createElement("script");
      script.id = "facebook-jssdk";
      script.src = "https://connect.facebook.net/en_US/sdk.js";
      script.async = true;
      script.defer = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error("Meta SDK failed to load"));
      document.head.appendChild(script);
    });
  }
  if (!window.FB) throw new Error("Meta SDK is unavailable");
  window.FB.init({ appId, cookie: true, xfbml: false, version: "v25.0" });
  return window.FB;
}
