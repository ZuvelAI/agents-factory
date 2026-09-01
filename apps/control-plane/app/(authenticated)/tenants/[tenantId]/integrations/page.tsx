import Link from "next/link";

import { TenantSectionPlaceholder } from "../../../../../components/tenant-section-placeholder";

export default async function TenantIntegrationsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  return (
    <>
      <TenantSectionPlaceholder
        eyebrow="Guided setup"
        title="Integrations"
        description="Connect the tenant-owned provider accounts through supported onboarding flows."
      />
      <p className="section-followup">
        WhatsApp onboarding is already available.{" "}
        <Link href={`/tenants/${tenantId}/whatsapp`}>Open WhatsApp setup</Link>
      </p>
    </>
  );
}
