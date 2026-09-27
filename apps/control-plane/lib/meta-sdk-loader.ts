export type MetaLoginResponse = { authResponse?: { code?: string } };

export type MetaSdk = {
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

const scriptWaiters = new WeakMap<
  Element,
  { active: number; owned: boolean }
>();

export async function loadMetaSdk(
  appId: string,
  signal: AbortSignal,
): Promise<MetaSdk> {
  if (signal.aborted) throw new Error("Meta SDK loading was cancelled");
  if (!window.FB) await waitForMetaSdk(signal);
  if (signal.aborted) throw new Error("Meta SDK loading was cancelled");
  const sdk = window.FB;
  if (!sdk) throw new Error("Meta SDK is unavailable");
  sdk.init({ appId, cookie: true, xfbml: false, version: "v25.0" });
  return sdk;
}

function waitForMetaSdk(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.getElementById("facebook-jssdk");
    const script = existing ?? document.createElement("script");
    const created = !existing;
    const waiters = scriptWaiters.get(script) ?? {
      active: 0,
      owned: created,
    };
    scriptWaiters.set(script, waiters);
    waiters.active += 1;
    if (created) {
      script.id = "facebook-jssdk";
      (script as HTMLScriptElement).src =
        "https://connect.facebook.net/en_US/sdk.js";
      (script as HTMLScriptElement).async = true;
      (script as HTMLScriptElement).defer = true;
    }
    let settled = false;
    const timeout = setTimeout(
      () => fail(new Error("Meta SDK loading timed out"), true),
      15_000,
    );
    function cleanup() {
      clearTimeout(timeout);
      waiters.active -= 1;
      signal.removeEventListener("abort", abort);
      script.removeEventListener("load", loaded);
      script.removeEventListener("error", failed);
    }
    function fail(error: Error, removeScript: boolean) {
      if (settled) return;
      settled = true;
      cleanup();
      if (removeScript) script.remove();
      reject(error);
    }
    function loaded() {
      if (settled) return;
      if (!window.FB) {
        fail(new Error("Meta SDK is unavailable"), true);
        return;
      }
      settled = true;
      cleanup();
      resolve();
    }
    function failed() {
      fail(new Error("Meta SDK failed to load"), true);
    }
    function abort() {
      fail(
        new Error("Meta SDK loading was cancelled"),
        waiters.owned && waiters.active === 1,
      );
    }
    script.addEventListener("load", loaded, { once: true });
    script.addEventListener("error", failed, { once: true });
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) {
      abort();
    } else if (window.FB) {
      loaded();
    } else if (created) {
      document.head.appendChild(script);
    }
  });
}
