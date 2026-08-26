import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { logout } from "../actions";
import {
  createServerSupabaseClient,
  getVerifiedPlatformAdmin,
} from "../../lib/auth";

const navigation = [
  "Dashboard",
  "Tenants",
  "Agents",
  "Capabilities",
  "Integrations",
  "Knowledge",
  "Conversations",
  "Cases",
  "Evals",
  "Usage & Costs",
  "Operations",
  "Settings",
] as const;

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
        <strong>Agents Factory</strong>
        <form action={logout}>
          <button type="submit">Sign out</button>
        </form>
      </header>
      <aside>
        <nav aria-label="Control Plane">
          <ul>
            {navigation.map((label) => (
              <li key={label}>{label}</li>
            ))}
          </ul>
        </nav>
      </aside>
      <main className="private-content">{children}</main>
    </div>
  );
}
