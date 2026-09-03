import Link from "next/link";
import type { ReactNode } from "react";
import { notFound } from "next/navigation";

import { ErrorState } from "../../../../components/error-state";
import { BackendProblem, callAuthenticatedBackend } from "../../../../lib/api";
import type { Tenant } from "../../../../lib/tenant";

const tabs = [
  ["Overview", ""],
  ["Onboarding", "/onboarding/company"],
  ["Agent", "/agent"],
  ["Capabilities", "/capabilities"],
  ["Integrations", "/integrations"],
  ["Knowledge", "/knowledge"],
  ["Conversations", "/conversations"],
  ["Test Console", "/test-console"],
  ["Cases", "/cases"],
  ["Usage", "/usage"],
  ["Settings", "/settings"],
] as const;

export default async function TenantLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  let tenant: Tenant;
  try {
    tenant = await callAuthenticatedBackend<Tenant>(
      `/admin/tenants/${encodeURIComponent(tenantId)}`,
    );
  } catch (error) {
    if (error instanceof BackendProblem && error.status === 404) notFound();
    return (
      <ErrorState
        title="Tenant unavailable"
        description="This tenant could not be loaded."
        correlationId={
          error instanceof BackendProblem ? error.correlationId : undefined
        }
      />
    );
  }
  return (
    <div className="tenant-workspace">
      <header className="tenant-header">
        <div>
          <p className="eyebrow">Tenant setup</p>
          <h1>{tenant.name}</h1>
          <p>
            {tenant.industry ?? "Industry pending"} · {tenant.slug}
          </p>
        </div>
        <span className={`tenant-status tenant-status-${tenant.status}`}>
          {tenant.status}
        </span>
      </header>
      <nav className="tenant-tabs" aria-label={`${tenant.name} configuration`}>
        {tabs.map(([label, suffix]) => (
          <Link href={`/tenants/${tenantId}${suffix}`} key={label}>
            {label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}
