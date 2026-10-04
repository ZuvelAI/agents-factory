import { redirect } from "next/navigation";
import { createServerSupabaseClient } from "../../lib/auth";
import { hasReviewAccess } from "../../lib/review-access";
import { getReviewBinding } from "../../lib/review-config";
import { reviewLogout } from "./actions";
import { ReviewPanel } from "./panel";

export default async function ReviewPage() {
  const client = await createServerSupabaseClient();
  const { data, error } = await client.auth.getUser();
  const binding = getReviewBinding();
  if (!binding || error || !hasReviewAccess(data.user))
    redirect("/review/login");
  return (
    <main style={{ maxWidth: 960, margin: "48px auto", padding: 24 }}>
      <h1>AI Workers — WhatsApp review</h1>
      <p>Test WhatsApp Business Account · API only</p>
      <p>
        WABA: {binding.wabaId} · Phone number ID: {binding.phoneNumberId}
      </p>
      <p>
        This account can load approved templates and submit a test message. It
        cannot access other clients, change credentials, revoke connections or
        administer the platform.
      </p>
      <ReviewPanel recipientHint={binding.recipient.slice(-4)} />
      <form action={reviewLogout}>
        <button type="submit">Sign out</button>
      </form>
    </main>
  );
}
