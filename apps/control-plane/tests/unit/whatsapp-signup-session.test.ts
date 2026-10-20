import { afterEach, describe, expect, it, vi } from "vitest";
import { runSignupSession } from "../../lib/whatsapp-signup-session";

const finish = {
  type: "WA_EMBEDDED_SIGNUP",
  event: "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
  data: { waba_id: "123" },
};

function setup(expiresAt = new Date(Date.now() + 1_800_000).toISOString()) {
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
    expiresAt,
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
    await vi.advanceTimersByTimeAsync(1_800_000);
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });
  it("does not accept spoofed assets", async () => {
    vi.useFakeTimers();
    const s = setup();
    s.respond("code");
    s.emit(finish, "https://attacker.test");
    const rejected = expect(s.promise).rejects.toThrow("timed out");
    await vi.advanceTimersByTimeAsync(1_800_000);
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
        new Date(Date.now() + 1_800_000).toISOString(),
      ),
    ).rejects.toThrow("SDK failure");
    expect(remove).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each([true, false])(
    "accepts completion after twenty minutes (%s)",
    async (codeFirst) => {
      vi.useFakeTimers();
      const s = setup();
      const result = expect(s.promise).resolves.toMatchObject({
        code: "late-code",
      });
      await vi.advanceTimersByTimeAsync(1_200_000);
      if (codeFirst) s.respond("late-code");
      s.emit();
      if (!codeFirst) s.respond("late-code");
      await result;
      expect(vi.getTimerCount()).toBe(0);
    },
  );
  it("uses the remaining server lifetime rather than restarting thirty minutes", async () => {
    vi.useFakeTimers();
    const s = setup(new Date(Date.now() + 60_000).toISOString());
    const result = expect(s.promise).rejects.toThrow("timed out");
    await vi.advanceTimersByTimeAsync(60_000);
    await result;
    s.respond("too-late");
    s.emit();
    expect(s.remove).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(["invalid", "2020-01-01T00:00:00Z"])(
    "does not open Meta with an invalid or expired deadline (%s)",
    async (expiresAt) => {
      vi.useFakeTimers();
      let opened = false;
      await expect(
        runSignupSession(
          {
            login() {
              opened = true;
            },
          },
          new EventTarget(),
          "config",
          "COEXISTENCE",
          new AbortController().signal,
          expiresAt,
        ),
      ).rejects.toThrow("expired");
      expect(opened).toBe(false);
      expect(vi.getTimerCount()).toBe(0);
    },
  );
  it("rejects expired callbacks even when the browser throttles the timer", async () => {
    vi.useFakeTimers();
    const deadline = Date.now() + 1_800_000;
    const s = setup(new Date(deadline).toISOString());
    const result = expect(s.promise).rejects.toThrow("timed out");
    vi.setSystemTime(deadline);
    s.respond("expired-code");
    s.emit();
    await result;
    expect(vi.getTimerCount()).toBe(0);
  });
});
