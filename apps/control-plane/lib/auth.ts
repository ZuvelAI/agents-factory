import { createServerClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";

type Claims = Record<string, unknown> & { sub?: string };

type ClaimsClient = {
  auth: {
    getClaims: () => Promise<{
      data: { claims?: unknown } | null;
      error: unknown;
    }>;
  };
};

type PasswordClient = ClaimsClient & {
  auth: ClaimsClient["auth"] & {
    signInWithPassword: (credentials: PasswordCredentials) => Promise<{
      data: { session: unknown | null };
      error: unknown;
    }>;
    signOut: () => Promise<{ error: unknown }>;
  };
};

type SignOutClient = {
  auth: {
    signOut: () => Promise<{ error: unknown }>;
  };
};

export type PasswordCredentials = {
  email: string;
  ["password"]: string;
};

export type AuthenticationResult =
  | { ok: true }
  | { ok: false; message: "Unable to sign in." };

function publicSupabaseEnvironment(): { url: string; publishableKey: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !publishableKey) {
    throw new Error("Supabase public authentication configuration is missing.");
  }
  return { url, publishableKey };
}

export async function createServerSupabaseClient(): Promise<SupabaseClient> {
  const cookieStore = await cookies();
  const { url, publishableKey } = publicSupabaseEnvironment();
  return createServerClient(url, publishableKey, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (cookiesToSet) => {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Server Components cannot persist refreshed cookies; Proxy owns refresh.
        }
      },
    },
  });
}

export function hasPlatformAdminRole(claims: unknown): claims is Claims {
  if (claims === null || typeof claims !== "object") return false;
  const appMetadata = (claims as Record<string, unknown>).app_metadata;
  return (
    appMetadata !== null &&
    typeof appMetadata === "object" &&
    (appMetadata as Record<string, unknown>).platform_role === "platform_admin"
  );
}

export async function getVerifiedPlatformAdmin(
  client: ClaimsClient,
): Promise<Claims | null> {
  const { data, error } = await client.auth.getClaims();
  if (error || !hasPlatformAdminRole(data?.claims)) return null;
  return data.claims;
}

export async function authenticateWithPassword(
  client: PasswordClient,
  credentials: PasswordCredentials,
): Promise<AuthenticationResult> {
  const { data, error } = await client.auth.signInWithPassword(credentials);
  if (error || !data.session) {
    return { ok: false, message: "Unable to sign in." };
  }

  const claims = await getVerifiedPlatformAdmin(client);
  if (!claims) {
    await client.auth.signOut();
    return { ok: false, message: "Unable to sign in." };
  }
  return { ok: true };
}

export async function signOutServerSession(
  client: SignOutClient,
): Promise<boolean> {
  const { error } = await client.auth.signOut();
  return error === null;
}
