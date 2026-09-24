import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";

import { logout } from "../actions";
import { ControlPlaneNavigation } from "../../components/control-plane-navigation";
import { UiIcon } from "../../components/ui-icon";
import {
  createServerSupabaseClient,
  getVerifiedPlatformAdmin,
} from "../../lib/auth";

export default async function AuthenticatedLayout({
  children,
}: {
  children: ReactNode;
}) {
  const client = await createServerSupabaseClient();
  if (!(await getVerifiedPlatformAdmin(client))) redirect("/login");

  return (
    <div className="control-plane-shell">
      <header className="topbar">
        <Link href="/" className="brand-lockup" aria-label="Zuvel — inicio">
          <Image
            src="/brand/zuvel-wordmark.png"
            alt="zuvel."
            width={120}
            height={37}
            unoptimized
            priority
          />
        </Link>
        <div className="topbar-product">
          <span>Workspace</span>
          <span className="breadcrumb-divider">/</span>
          <strong>Agents Factory</strong>
        </div>
        <span className="topbar-label">
          <UiIcon name="lock" size={14} /> Control Plane
        </span>
        <form action={logout}>
          <button className="ghost-button" type="submit">
            <UiIcon name="logout" size={16} /> Sign out
          </button>
        </form>
      </header>
      <aside className="app-sidebar">
        <div className="workspace-identity">
          <span className="product-mark">
            <UiIcon name="agents" size={23} />
          </span>
          <div>
            <strong>Agents Factory</strong>
            <small>Tu espacio de trabajo</small>
          </div>
        </div>
        <ControlPlaneNavigation />
        <div className="sidebar-footer">
          <span className="brand-node" />
          <p>
            Sistemas digitales
            <br />
            para empresas con IA
          </p>
        </div>
      </aside>
      <main className="private-content">{children}</main>
    </div>
  );
}
