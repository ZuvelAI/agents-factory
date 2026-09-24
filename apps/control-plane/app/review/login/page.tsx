import { reviewLogin } from "../actions";

export default async function ReviewLogin({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <main style={{ maxWidth: 560, margin: "80px auto", padding: 24 }}>
    <h1>AI Workers — Meta review</h1>
    <p>Restricted access to the WhatsApp test account.</p>
    {error && <p role="alert">Unable to sign in with these review credentials.</p>}
    <form action={reviewLogin}>
      <p><label>Email <input name="email" type="email" autoComplete="username" required /></label></p>
      <p><label>Password <input name="password" type="password" autoComplete="current-password" required /></label></p>
      <button type="submit">Sign in</button>
    </form>
  </main>;
}
