import { redirect } from "next/navigation";
import Image from "next/image";
import { UiIcon } from "../../components/ui-icon";

import { login } from "../actions";
import {
  createServerSupabaseClient,
  getVerifiedPlatformAdmin,
} from "../../lib/auth";

type LoginPageProps = {
  searchParams: Promise<{ error?: string }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const client = await createServerSupabaseClient();
  if (await getVerifiedPlatformAdmin(client)) redirect("/");
  const { error } = await searchParams;

  return (
    <main className="login-shell">
      <section className="login-card" aria-labelledby="login-title">
        <Image
          className="login-wordmark"
          src="/brand/zuvel-wordmark.png"
          alt="zuvel."
          width={140}
          height={43}
          unoptimized
          priority
        />
        <p className="eyebrow">Private Control Plane</p>
        <h1 id="login-title">Agents Factory</h1>
        <p>Sign in with your platform administrator account.</p>
        {error ? <p role="alert">Unable to sign in.</p> : null}
        <form action={login} className="login-form">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
          <button type="submit">
            Sign in <UiIcon name="arrow" size={18} />
          </button>
        </form>
        <p className="login-footnote">
          <UiIcon name="lock" size={14} /> Acceso exclusivo para administradores
        </p>
      </section>
    </main>
  );
}
