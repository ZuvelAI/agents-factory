export function hasReviewAccess(user: unknown): boolean {
  if (!user || typeof user !== "object") return false;
  const metadata = (user as { app_metadata?: Record<string, unknown> }).app_metadata;
  const scope = metadata?.review_access as Record<string, unknown> | undefined;
  return metadata?.platform_role === "meta_reviewer" &&
    scope?.tenant_id === "c5cd8d04-01f2-49be-aa27-1075520a2a20" &&
    scope?.account_id === "d4dfa61a-7ed6-4a87-877a-1d34e7dbf837" &&
    typeof scope?.expires_at === "string" && Date.parse(scope.expires_at) > Date.now();
}
