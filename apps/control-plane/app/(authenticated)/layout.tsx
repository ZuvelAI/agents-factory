import type { ReactNode } from "react";
import { redirect } from "next/navigation";

import { logout } from "../actions";
import { AppShell } from "../../components/layout";
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

  return <AppShell signOutAction={logout}>{children}</AppShell>;
}
