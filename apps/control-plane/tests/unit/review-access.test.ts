import { describe, it, expect } from "vitest";
import { hasReviewAccess } from "../../lib/review-access";
import { hasPlatformAdminRole } from "../../lib/auth";

const metadata = { platform_role: "meta_reviewer", review_access: {
  tenant_id: "c5cd8d04-01f2-49be-aa27-1075520a2a20",
  account_id: "d4dfa61a-7ed6-4a87-877a-1d34e7dbf837",
  expires_at: "2099-01-01T00:00:00Z",
} };
describe("restricted review", () => {
  it("does not grant admin", () => {
    expect(hasReviewAccess({ app_metadata: metadata })).toBe(true);
    expect(hasPlatformAdminRole({ app_metadata: metadata })).toBe(false);
  });
  it("rejects editable metadata", () => expect(hasReviewAccess({ user_metadata: metadata })).toBe(false));
  it("rejects different scope and expired access", () => {
    for (const change of [{ tenant_id: "other" }, { account_id: "other" }, { expires_at: "2020-01-01" }]) {
      expect(hasReviewAccess({ app_metadata: { ...metadata, review_access: { ...metadata.review_access, ...change } } })).toBe(false);
    }
  });
});
