import { redirect } from "next/navigation";

import { callAuthenticatedBackend } from "../../../../../lib/api";
import type { Onboarding } from "../../../../../lib/onboarding";

export default async function TenantOnboardingPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  const onboarding = await callAuthenticatedBackend<Onboarding>(
    `/admin/tenants/${encodeURIComponent(tenantId)}/onboarding`,
  );
  redirect(`/tenants/${tenantId}/onboarding/${onboarding.current_step}`);
}
