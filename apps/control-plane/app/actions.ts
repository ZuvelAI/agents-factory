"use server";

import { redirect } from "next/navigation";

import {
  authenticateWithPassword,
  createServerSupabaseClient,
  signOutServerSession,
} from "../lib/auth";

export async function login(formData: FormData): Promise<void> {
  const email = formData.get("email");
  const submittedPassword = formData.get("password");
  if (typeof email !== "string" || typeof submittedPassword !== "string") {
    redirect("/login?error=invalid");
  }

  const client = await createServerSupabaseClient();
  const result = await authenticateWithPassword(client, {
    email,
    ["password"]: submittedPassword,
  });
  if (!result.ok) redirect("/login?error=invalid");
  redirect("/");
}

export async function logout(): Promise<void> {
  const client = await createServerSupabaseClient();
  await signOutServerSession(client);
  redirect("/login");
}
