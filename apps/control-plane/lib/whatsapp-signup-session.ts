import type { WhatsAppMode } from "./whatsapp-mode";
import {
  parseSignupEvent,
  type EmbeddedSignupAssets,
} from "./whatsapp-signup-event";

export type MetaLoginResponse = { authResponse?: { code?: string } };
export type LoginSdk = {
  login(
    callback: (response: MetaLoginResponse) => void,
    options: Record<string, unknown>,
  ): void;
};

export function runSignupSession(
  sdk: LoginSdk,
  events: EventTarget,
  configurationId: string,
  mode: WhatsAppMode,
  signal: AbortSignal,
  expiresAt: string,
): Promise<{ code: string; assets: EmbeddedSignupAssets }> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error("Meta authorization was cancelled"));
      return;
    }
    const deadline = Date.parse(expiresAt);
    const remaining = deadline - Date.now();
    if (!Number.isFinite(deadline) || remaining <= 0) {
      reject(
        new Error(
          "Meta authorization session expired. Start a new connection.",
        ),
      );
      return;
    }
    let settled = false;
    let code: string | undefined;
    let assets: EmbeddedSignupAssets | null = null;
    const timeout = setTimeout(
      () => fail(new Error("Meta signup timed out")),
      remaining,
    );
    function cleanup() {
      settled = true;
      clearTimeout(timeout);
      events.removeEventListener("message", receive);
      signal.removeEventListener("abort", abort);
    }
    function fail(error: unknown) {
      if (settled) return;
      cleanup();
      reject(error);
    }
    function abort() {
      fail(new Error("Meta authorization was cancelled"));
    }
    function complete() {
      if (settled) return;
      if (Date.now() >= deadline) {
        fail(new Error("Meta signup timed out"));
        return;
      }
      if (!code || !assets) return;
      cleanup();
      resolve({ code, assets });
    }
    function receive(event: Event) {
      if (settled || !(event instanceof MessageEvent)) return;
      assets = parseSignupEvent(event.origin, event.data, mode) ?? assets;
      complete();
    }
    events.addEventListener("message", receive);
    signal.addEventListener("abort", abort, { once: true });
    try {
      sdk.login(
        (response) => {
          if (settled) return;
          code = response.authResponse?.code;
          if (!code) abort();
          else complete();
        },
        {
          config_id: configurationId,
          response_type: "code",
          override_default_response_type: true,
          extras: {
            sessionInfoVersion: "3",
            ...(mode === "COEXISTENCE"
              ? { featureType: "whatsapp_business_app_onboarding" }
              : {}),
          },
        },
      );
    } catch (error) {
      fail(error);
    }
  });
}
