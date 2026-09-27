import { afterEach, describe, expect, it, vi } from "vitest";

import { loadMetaSdk } from "../../lib/meta-sdk-loader";

class FakeScript extends EventTarget {
  id = "";
  src = "";
  async = false;
  defer = false;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  removed = false;

  remove() {
    this.removed = true;
  }
}

function setup() {
  const scripts: FakeScript[] = [];
  const fakeDocument = {
    getElementById: () => scripts.find((script) => !script.removed) ?? null,
    createElement: () => new FakeScript(),
    head: {
      appendChild(script: FakeScript) {
        scripts.push(script);
      },
    },
  };
  const fakeWindow: { FB?: { init: ReturnType<typeof vi.fn> } } = {};
  vi.stubGlobal("document", fakeDocument);
  vi.stubGlobal("window", fakeWindow);
  return { scripts, fakeWindow };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Meta SDK loading", () => {
  it("cancels an in-flight load and lets a later attempt retry", async () => {
    const { scripts, fakeWindow } = setup();
    const controller = new AbortController();
    const first = loadMetaSdk("app-1", controller.signal);
    expect(scripts).toHaveLength(1);

    controller.abort();
    await expect(first).rejects.toThrow("cancelled");
    expect(scripts[0].removed).toBe(true);

    const next = loadMetaSdk("app-1", new AbortController().signal);
    expect(scripts).toHaveLength(2);
    fakeWindow.FB = { init: vi.fn() };
    scripts[1].dispatchEvent(new Event("load"));
    await expect(next).resolves.toBe(fakeWindow.FB);
    expect(fakeWindow.FB.init).toHaveBeenCalledWith({
      appId: "app-1",
      cookie: true,
      xfbml: false,
      version: "v25.0",
    });
  });

  it("removes a failed script so the user can retry", async () => {
    const { scripts } = setup();
    const first = loadMetaSdk("app-1", new AbortController().signal);
    scripts[0].dispatchEvent(new Event("error"));
    await expect(first).rejects.toThrow("failed to load");
    expect(scripts[0].removed).toBe(true);

    const second = loadMetaSdk("app-1", new AbortController().signal);
    expect(scripts).toHaveLength(2);
    scripts[1].dispatchEvent(new Event("error"));
    await expect(second).rejects.toThrow("failed to load");
  });

  it("does not remove a shared script when only a later waiter cancels", async () => {
    const { scripts, fakeWindow } = setup();
    const first = loadMetaSdk("app-1", new AbortController().signal);
    const laterController = new AbortController();
    const later = loadMetaSdk("app-1", laterController.signal);

    expect(scripts).toHaveLength(1);
    laterController.abort();
    await expect(later).rejects.toThrow("cancelled");
    expect(scripts[0].removed).toBe(false);

    fakeWindow.FB = { init: vi.fn() };
    scripts[0].dispatchEvent(new Event("load"));
    await expect(first).resolves.toBe(fakeWindow.FB);
  });

  it("keeps a shared script alive if its original waiter cancels", async () => {
    const { scripts, fakeWindow } = setup();
    const originalController = new AbortController();
    const original = loadMetaSdk("app-1", originalController.signal);
    const later = loadMetaSdk("app-1", new AbortController().signal);

    originalController.abort();
    await expect(original).rejects.toThrow("cancelled");
    expect(scripts[0].removed).toBe(false);

    fakeWindow.FB = { init: vi.fn() };
    scripts[0].dispatchEvent(new Event("load"));
    await expect(later).resolves.toBe(fakeWindow.FB);
  });

  it("times out if a preexisting script never completes", async () => {
    vi.useFakeTimers();
    const { scripts } = setup();
    const hanging = new FakeScript();
    scripts.push(hanging);

    const pending = loadMetaSdk("app-1", new AbortController().signal);
    const rejected = expect(pending).rejects.toThrow("timed out");
    await vi.advanceTimersByTimeAsync(15_000);
    await rejected;
    expect(hanging.removed).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
