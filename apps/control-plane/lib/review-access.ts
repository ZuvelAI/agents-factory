import "server-only";
import { getReviewBinding } from "./review-config";

export function hasReviewAccess(user: unknown): boolean {
  if (!user || typeof user !== "object") return false;
  if ((user as { is_anonymous?: unknown }).is_anonymous === true) return false;
  const binding = getReviewBinding();
  if (!binding) return false;
  const metadata = (user as { app_metadata?: Record<string, unknown> })
    .app_metadata;
  const scope = metadata?.review_access as Record<string, unknown> | undefined;
  return (
    metadata?.platform_role === "meta_reviewer" &&
    scope?.tenant_id === binding.tenantId &&
    scope?.account_id === binding.accountId &&
    typeof scope?.expires_at === "string" &&
    /(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(scope.expires_at) &&
    Date.parse(scope.expires_at) > Date.now()
  );
}
