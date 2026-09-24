import { redirect } from "next/navigation";
import { createServerSupabaseClient } from "../../lib/auth";
import { hasReviewAccess } from "../../lib/review-access";
import { reviewLogout } from "./actions";
import { ReviewPanel } from "./panel";

export default async function ReviewPage() {
  const client = await createServerSupabaseClient();
  const { data, error } = await client.auth.getUser();
  if (error || !hasReviewAccess(data.user)) redirect("/review/login");
  return <main style={{ maxWidth: 960, margin: "48px auto", padding: 24 }}>
    <h1>AI Workers — WhatsApp review</h1>
    <p>Test WhatsApp Business Account · API only</p>
    <p>WABA: 1894805611498111 · Phone number ID: 1334721596385520</p>
    <p>This account can load approved templates and submit a test message. It cannot access other clients, change credentials, revoke connections or administer the platform.</p>
    <ReviewPanel />
    <form action={reviewLogout}><button type="submit">Sign out</button></form>
  </main>;
}
