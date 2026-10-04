import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { hasReviewAccess } from "../../lib/review-access";
import { hasPlatformAdminRole } from "../../lib/auth";

const metadata = {
  platform_role: "meta_reviewer",
  review_access: {
    tenant_id: "c5cd8d04-01f2-49be-aa27-1075520a2a20",
    account_id: "d4dfa61a-7ed6-4a87-877a-1d34e7dbf837",
    expires_at: "2099-01-01T00:00:00Z",
  },
};

beforeEach(() => {
  vi.stubEnv("META_REVIEW_TENANT_ID", "c5cd8d04-01f2-49be-aa27-1075520a2a20");
  vi.stubEnv("META_REVIEW_ACCOUNT_ID", "d4dfa61a-7ed6-4a87-877a-1d34e7dbf837");
  vi.stubEnv("META_REVIEW_WABA_ID", "1894805611498111");
  vi.stubEnv("META_REVIEW_PHONE_NUMBER_ID", "1334721596385520");
  vi.stubEnv("META_REVIEW_RECIPIENT", "573103538756");
});
afterEach(() => vi.unstubAllEnvs());

describe("restricted review", () => {
  it("denies review when the server binding is incomplete", () => {
    vi.stubEnv("META_REVIEW_ACCOUNT_ID", "");
    expect(hasReviewAccess({ app_metadata: metadata })).toBe(false);
  });
  it("compares metadata to the configured server binding, not a built-in customer", () => {
    vi.stubEnv("META_REVIEW_TENANT_ID", "11111111-1111-4111-8111-111111111111");
    vi.stubEnv(
      "META_REVIEW_ACCOUNT_ID",
      "22222222-2222-4222-8222-222222222222",
    );
    expect(hasReviewAccess({ app_metadata: metadata })).toBe(false);
    expect(
      hasReviewAccess({
        app_metadata: {
          ...metadata,
          review_access: {
            ...metadata.review_access,
            tenant_id: "11111111-1111-4111-8111-111111111111",
            account_id: "22222222-2222-4222-8222-222222222222",
          },
        },
      }),
    ).toBe(true);
  });
  it("rejects anonymous accounts", () => {
    expect(
      hasReviewAccess({ app_metadata: metadata, is_anonymous: true }),
    ).toBe(false);
  });
  it("does not grant admin", () => {
    expect(hasReviewAccess({ app_metadata: metadata })).toBe(true);
    expect(hasPlatformAdminRole({ app_metadata: metadata })).toBe(false);
  });
  it("rejects editable metadata", () =>
    expect(hasReviewAccess({ user_metadata: metadata })).toBe(false));
  it("rejects different scope and expired access", () => {
    for (const change of [
      { tenant_id: "other" },
      { account_id: "other" },
      { expires_at: "2020-01-01" },
      { expires_at: "2099-01-01T00:00:00" },
    ]) {
      expect(
        hasReviewAccess({
          app_metadata: {
            ...metadata,
            review_access: { ...metadata.review_access, ...change },
          },
        }),
      ).toBe(false);
    }
  });
  it.each([
    "META_REVIEW_TENANT_ID",
    "META_REVIEW_ACCOUNT_ID",
    "META_REVIEW_WABA_ID",
    "META_REVIEW_PHONE_NUMBER_ID",
    "META_REVIEW_RECIPIENT",
  ])("rejects malformed server configuration in %s", (name) => {
    vi.stubEnv(name, "invalid-input");
    expect(hasReviewAccess({ app_metadata: metadata })).toBe(false);
  });
});
