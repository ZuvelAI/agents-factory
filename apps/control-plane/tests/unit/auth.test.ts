import { afterEach, describe, expect, it, vi } from "vitest";

import {
  authenticateWithPassword,
  getVerifiedPlatformAdmin,
  hasPlatformAdminRole,
  signOutServerSession,
} from "../../lib/auth";
import { callBackend } from "../../lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("platform admin claims", () => {
  it("accepts only the nested signed app_metadata role", () => {
    expect(
      hasPlatformAdminRole({
        app_metadata: { platform_role: "platform_admin" },
      }),
    ).toBe(true);
    expect(
      hasPlatformAdminRole({
        app_metadata: {},
        user_metadata: { platform_role: "platform_admin" },
      }),
    ).toBe(false);
  });

  it("uses getClaims as the authorization authority", async () => {
    const getClaims = vi.fn().mockResolvedValue({
      data: {
        claims: {
          sub: "00000000-0000-4000-8000-000000000001",
          app_metadata: { platform_role: "platform_admin" },
        },
      },
      error: null,
    });

    const claims = await getVerifiedPlatformAdmin({ auth: { getClaims } });

    expect(claims?.sub).toBe("00000000-0000-4000-8000-000000000001");
    expect(getClaims).toHaveBeenCalledOnce();
  });

  it("fails closed when claims are missing or not platform_admin", async () => {
    for (const claims of [null, { app_metadata: {} }]) {
      const client = {
        auth: {
          getClaims: vi.fn().mockResolvedValue({
            data: { claims },
            error: null,
          }),
        },
      };
      await expect(getVerifiedPlatformAdmin(client)).resolves.toBeNull();
    }
  });
});

describe("password auth", () => {
  it("returns one generic error for invalid credentials", async () => {
    const signInWithPassword = vi.fn().mockResolvedValue({
      data: { session: null },
      error: new Error("provider detail must stay private"),
    });

    const result = await authenticateWithPassword(
      {
        auth: {
          signInWithPassword,
          getClaims: vi.fn(),
          signOut: vi.fn(),
        },
      },
      { email: "admin@example.test", ["password"]: "wrong" },
    );

    expect(result).toEqual({ ok: false, message: "Unable to sign in." });
    expect(JSON.stringify(result)).not.toContain("provider detail");
  });

  it("rejects a successful login when the signed role is absent", async () => {
    const signOut = vi.fn().mockResolvedValue({ error: null });
    const client = {
      auth: {
        signInWithPassword: vi.fn().mockResolvedValue({
          data: { session: { access_token: "opaque" } },
          error: null,
        }),
        getClaims: vi.fn().mockResolvedValue({
          data: { claims: { app_metadata: {} } },
          error: null,
        }),
        signOut,
      },
    };

    await expect(
      authenticateWithPassword(client, {
        email: "user@example.test",
        ["password"]: "valid-user",
      }),
    ).resolves.toEqual({ ok: false, message: "Unable to sign in." });
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("signs out through the server client", async () => {
    const signOut = vi.fn().mockResolvedValue({ error: null });

    await expect(signOutServerSession({ auth: { signOut } })).resolves.toBe(
      true,
    );

    expect(signOut).toHaveBeenCalledOnce();
  });
});

describe("server-only backend API", () => {
  it("rejects absolute or protocol-relative paths before network access", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    for (const path of [
      "https://attacker.invalid/data",
      "//attacker.invalid/data",
    ]) {
      await expect(
        callBackend("https://api.example.test", path, {
          accessToken: "verified-token",
        }),
      ).rejects.toMatchObject({ code: "backend_path_invalid" });
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards the verified bearer token and disables caching", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "tenant-1" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      callBackend("https://api.example.test", "/admin/tenants/tenant-1", {
        accessToken: "verified-token",
      }),
    ).resolves.toEqual({ id: "tenant-1" });

    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/admin/tenants/tenant-1",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer verified-token",
        }),
      }),
    );
  });

  it("maps problem details without returning unknown raw provider bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("upstream stack trace", {
          status: 502,
          headers: { "content-type": "text/plain" },
        }),
      ),
    );

    await expect(
      callBackend("https://api.example.test", "/admin/tenants/missing", {
        accessToken: "verified-token",
      }),
    ).rejects.toMatchObject({
      status: 502,
      code: "backend_request_failed",
      message: "The backend request could not be completed.",
    });
  });

  it("maps malformed problem JSON without exposing parser details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("{malformed", {
          status: 502,
          headers: { "content-type": "application/problem+json" },
        }),
      ),
    );

    await expect(
      callBackend("https://api.example.test", "/admin/tenants/missing", {
        accessToken: "verified-token",
      }),
    ).rejects.toMatchObject({
      status: 502,
      code: "backend_request_failed",
      message: "The backend request could not be completed.",
    });
  });
});
