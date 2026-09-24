"use server";

import { redirect } from "next/navigation";
import { createServerSupabaseClient } from "../../lib/auth";
import { callBackend, BackendProblem } from "../../lib/api";
import { hasReviewAccess } from "../../lib/review-access";

export async function reviewLogin(form: FormData) {
  const email = form.get("email");
  const password = form.get("password");
  if (typeof email !== "string" || typeof password !== "string") redirect("/review/login?error=1");
  const client = await createServerSupabaseClient();
  const { data, error } = await client.auth.signInWithPassword({ email, password });
  if (error || !hasReviewAccess(data.user)) {
    await client.auth.signOut();
    redirect("/review/login?error=1");
  }
  redirect("/review");
}

export async function reviewLogout() {
  const client = await createServerSupabaseClient();
  await client.auth.signOut();
  redirect("/review/login");
}

async function requestReview<T>(path: "/templates" | "/messages", body?: unknown) {
  try {
    const client = await createServerSupabaseClient();
    const { data: user, error } = await client.auth.getUser();
    if (error || !hasReviewAccess(user.user)) return { ok: false as const, message: "Review access expired or unavailable." };
    const { data } = await client.auth.getSession();
    if (!data.session) return { ok: false as const, message: "Sign in again." };
    const baseUrl = process.env.BACKEND_API_URL;
    if (!baseUrl) return { ok: false as const, message: "Service unavailable." };
    const result = await callBackend<T>(baseUrl, `/review/whatsapp${path}`, {
      method: "POST", accessToken: data.session.access_token,
      headers: { "Content-Type": "application/json" },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    return { ok: true as const, data: result };
  } catch (error) {
    return { ok: false as const, message: error instanceof BackendProblem ? error.message : "Service unavailable. Please try again." };
  }
}

export async function reviewTemplates() {
  return requestReview<{ name: string; language: string }[]>("/templates");
}

export async function reviewSend(name: string, language: string, idempotencyKey: string) {
  return requestReview<{ id: string; status: string }>("/messages", {
    recipient: "573103538756", template_name: name, language,
    idempotency_key: idempotencyKey,
  });
}
