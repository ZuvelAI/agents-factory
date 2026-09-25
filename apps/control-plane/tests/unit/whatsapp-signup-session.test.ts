import { afterEach, describe, expect, it, vi } from "vitest";
import { runSignupSession } from "../../lib/whatsapp-signup-session";

const finish = {
  type: "WA_EMBEDDED_SIGNUP",
  event: "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
  data: { waba_id: "123" },
};

function setup() {
  const events = new EventTarget();
  const controller = new AbortController();
  let callback: (response: {
    authResponse?: { code?: string };
  }) => void = () => {};
  let options: Record<string, unknown> = {};
  const sdk = {
    login(cb: typeof callback, opts: Record<string, unknown>) {
      callback = cb;
      options = opts;
    },
  };
  const remove = vi.spyOn(events, "removeEventListener");
  const promise = runSignupSession(
    sdk,
    events,
    "config",
    "COEXISTENCE",
    controller.signal,
  );
  const emit = (data = finish, origin = "https://www.facebook.com") =>
    events.dispatchEvent(new MessageEvent("message", { origin, data }));
  return {
    promise,
    emit,
    controller,
    remove,
    respond: (code?: string) => callback({ authResponse: { code } }),
    options,
  };
}

afterEach(() => vi.useRealTimers());
describe("signup session lifetime", () => {
  it.each([true, false])(
    "joins authorization and assets in either order (%s)",
    async (codeFirst) => {
      vi.useFakeTimers();
      const s = setup();
      if (codeFirst) s.respond("code");
      s.emit();
      if (!codeFirst) s.respond("code");
      await expect(s.promise).resolves.toEqual({
        code: "code",
        assets: { wabaId: "123", businessId: null, phoneNumberId: null },
      });
      expect(s.remove).toHaveBeenCalledOnce();
      expect(vi.getTimerCount()).toBe(0);
      expect(s.options).toMatchObject({
        config_id: "config",
        response_type: "code",
        extras: {
          featureType: "whatsapp_business_app_onboarding",
          sessionInfoVersion: "3",
        },
      });
    },
  );
  it("cleans up immediately when Meta authorization is cancelled", async () => {
    vi.useFakeTimers();
    const s = setup();
    s.respond();
    await expect(s.promise).rejects.toThrow("cancelled");
    expect(s.remove).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("aborts on unmount and ignores late callbacks", async () => {
    vi.useFakeTimers();
    const s = setup();
    s.controller.abort();
    s.respond("late");
    s.emit();
    await expect(s.promise).rejects.toThrow("cancelled");
    expect(s.remove).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("times out even if Meta returns assets but no authorization callback", async () => {
    vi.useFakeTimers();
    const s = setup();
    s.emit();
    const rejected = expect(s.promise).rejects.toThrow("timed out");
    await vi.advanceTimersByTimeAsync(120_000);
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });
  it("does not accept spoofed assets", async () => {
    vi.useFakeTimers();
    const s = setup();
    s.respond("code");
    s.emit(finish, "https://attacker.test");
    const rejected = expect(s.promise).rejects.toThrow("timed out");
    await vi.advanceTimersByTimeAsync(120_000);
    await rejected;
  });
  it("cleans up if SDK throws synchronously", async () => {
    vi.useFakeTimers();
    const events = new EventTarget();
    const remove = vi.spyOn(events, "removeEventListener");
    await expect(
      runSignupSession(
        {
          login() {
            throw new Error("SDK failure");
          },
        },
        events,
        "config",
        "API_ONLY",
        new AbortController().signal,
      ),
    ).rejects.toThrow("SDK failure");
    expect(remove).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
});
