"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { beginWhatsAppSignup, finishWhatsAppSignup } from "../../../../actions";

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

type EmbeddedSignupAssets = {
  businessId: string;
  wabaId: string;
  phoneNumberId: string;
};

export function EmbeddedSignup({ tenantId }: { tenantId: string }) {
  const router = useRouter();
  const [status, setStatus] = useState<"idle" | "working" | "error">("idle");
  const [message, setMessage] = useState("");

  async function connect() {
    setStatus("working");
    setMessage("Opening Meta Embedded Signup…");
    const started = await beginWhatsAppSignup(tenantId);
    if (!started.ok) {
      setStatus("error");
      setMessage(started.message);
      return;
    }

    try {
      const sdk = await loadMetaSdk(started.data.app_id);
      const assetsPromise = waitForEmbeddedSignupAssets();
      const codePromise = new Promise<string>((resolve, reject) => {
        sdk.login(
          (response) => {
            const code = response.authResponse?.code;
            if (code) resolve(code);
            else reject(new Error("Meta authorization was cancelled"));
          },
          {
            config_id: started.data.configuration_id,
            response_type: "code",
            override_default_response_type: true,
            extras: { sessionInfoVersion: "3" },
          },
        );
      });
      const [code, assets] = await Promise.all([codePromise, assetsPromise]);
      const finished = await finishWhatsAppSignup({
        tenantId,
        state: started.data.state,
        code,
        businessId: assets.businessId,
        wabaId: assets.wabaId,
        phoneNumberId: assets.phoneNumberId,
      });
      if (!finished.ok) throw new Error(finished.message);
      setStatus("idle");
      setMessage("WhatsApp connected.");
      router.refresh();
    } catch (error) {
      setStatus("error");
      setMessage(
        error instanceof Error
          ? error.message
          : "The WhatsApp connection could not be completed.",
      );
    }
  }

  return (
    <div className="signup-action">
      <button type="button" onClick={connect} disabled={status === "working"}>
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

function waitForEmbeddedSignupAssets(): Promise<EmbeddedSignupAssets> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error("Meta did not return the selected WhatsApp assets"));
    }, 120_000);
    function cleanup() {
      window.clearTimeout(timeout);
      window.removeEventListener("message", receive);
    }
    function receive(event: MessageEvent) {
      if (
        event.origin !== "https://www.facebook.com" &&
        event.origin !== "https://web.facebook.com"
      ) {
        return;
      }
      let payload: unknown = event.data;
      if (typeof payload === "string") {
        try {
          payload = JSON.parse(payload);
        } catch {
          return;
        }
      }
      if (!isEmbeddedSignupFinish(payload)) return;
      cleanup();
      resolve({
        businessId: payload.data.business_id,
        wabaId: payload.data.waba_id,
        phoneNumberId: payload.data.phone_number_id,
      });
    }
    window.addEventListener("message", receive);
  });
}

function isEmbeddedSignupFinish(value: unknown): value is {
  type: "WA_EMBEDDED_SIGNUP";
  event: "FINISH";
  data: { business_id: string; waba_id: string; phone_number_id: string };
} {
  if (value === null || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  if (
    candidate.type !== "WA_EMBEDDED_SIGNUP" ||
    candidate.event !== "FINISH" ||
    candidate.data === null ||
    typeof candidate.data !== "object"
  ) {
    return false;
  }
  const data = candidate.data as Record<string, unknown>;
  return (
    typeof data.business_id === "string" &&
    typeof data.waba_id === "string" &&
    typeof data.phone_number_id === "string"
  );
}
