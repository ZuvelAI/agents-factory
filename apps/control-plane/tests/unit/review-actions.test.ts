import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { reviewSend } from "../../app/review/actions";
import ReviewPage from "../../app/review/page";
import { createServerSupabaseClient } from "../../lib/auth";
import { callBackend } from "../../lib/api";

vi.mock("../../lib/auth", () => ({ createServerSupabaseClient: vi.fn() }));
vi.mock("../../lib/api", async (original) => ({
  ...(await original<typeof import("../../lib/api")>()),
  callBackend: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  redirect: () => {
    throw new Error("redirect");
  },
}));

const user = {
  id: "33333333-3333-4333-8333-333333333333",
  is_anonymous: false,
  app_metadata: {
    platform_role: "meta_reviewer",
    review_access: {
      tenant_id: "11111111-1111-4111-8111-111111111111",
      account_id: "22222222-2222-4222-8222-222222222222",
      expires_at: "2099-01-01T00:00:00Z",
    },
  },
};
const getUser = vi.fn();

beforeEach(() => {
  vi.stubEnv(
    "META_REVIEW_TENANT_ID",
    user.app_metadata.review_access.tenant_id,
  );
  vi.stubEnv(
    "META_REVIEW_ACCOUNT_ID",
    user.app_metadata.review_access.account_id,
  );
  vi.stubEnv("META_REVIEW_WABA_ID", "111111111111111");
  vi.stubEnv("META_REVIEW_PHONE_NUMBER_ID", "222222222222222");
  vi.stubEnv("META_REVIEW_RECIPIENT", "15550123456");
  vi.stubEnv("BACKEND_API_URL", "http://backend.invalid");
  getUser.mockReset().mockResolvedValue({ data: { user }, error: null });
  vi.mocked(createServerSupabaseClient).mockResolvedValue({
    auth: {
      getUser,
      getSession: vi
        .fn()
        .mockResolvedValue({
          data: { session: { access_token: "synthetic-session" } },
        }),
    },
  } as unknown as Awaited<ReturnType<typeof createServerSupabaseClient>>);
  vi.mocked(callBackend)
    .mockReset()
    .mockResolvedValue({ id: "message-id", status: "queued" });
});
afterEach(() => vi.unstubAllEnvs());

describe("server-bound review actions", () => {
  it("sends only the configured recipient after a fresh user check", async () => {
    expect(await reviewSend("hello_world", "en_US", "attempt-id")).toEqual({
      ok: true,
      data: { id: "message-id", status: "queued" },
    });
    expect(callBackend).toHaveBeenCalledWith(
      "http://backend.invalid",
      "/review/whatsapp/messages",
      expect.objectContaining({
        accessToken: "synthetic-session",
        body: JSON.stringify({
          recipient: "15550123456",
          template_name: "hello_world",
          language: "en_US",
          idempotency_key: "attempt-id",
        }),
      }),
    );
    expect(getUser).toHaveBeenCalledOnce();
  });
  it("denies a revoked scope before forwarding the session", async () => {
    getUser.mockResolvedValue({
      data: { user: { ...user, app_metadata: {} } },
      error: null,
    });
    expect((await reviewSend("hello_world", "en_US", "attempt-id")).ok).toBe(
      false,
    );
    expect(callBackend).not.toHaveBeenCalled();
  });
  it("denies missing configuration before any provider operation", async () => {
    vi.stubEnv("META_REVIEW_RECIPIENT", "");
    expect((await reviewSend("hello_world", "en_US", "attempt-id")).ok).toBe(
      false,
    );
    expect(callBackend).not.toHaveBeenCalled();
  });
  it("renders only the bound test assets and a masked recipient hint", async () => {
    const markup = renderToStaticMarkup(await ReviewPage());
    expect(markup).toContain("111111111111111");
    expect(markup).toContain("222222222222222");
    expect(markup).toContain("ending in 3456");
    expect(markup).not.toContain("15550123456");
    expect(markup).toContain("Maximum 10 test messages per day");
    expect(callBackend).not.toHaveBeenCalled();
  });
});
