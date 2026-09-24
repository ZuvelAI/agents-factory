# AI Workers: dual WhatsApp onboarding

## Release state (2026-09-09)

This is a partial implementation, NOT a working coexistence release.
Local UI provides explicit mode selection and exclusive-number confirmation.
Both start and complete endpoints reject COEXISTENCE with a stable pending
error. Keep the release gate until all items below are verified. Do not merely
remove the gate or set eligibility to ELIGIBLE to get past onboarding.
No production deployment or customer onboarding was performed for this change.

## Verified primary source

https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/

Read directly on 2026-09-09. The official flow can return
FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING with only a WABA ID. It is not the
standard FINISH payload. Resolve missing business/phone assets server-side and
let the user choose when ambiguous; never pick the first phone automatically.
Use is_on_biz_app=true AND platform_type=CLOUD_API to confirm coexistence,
with authenticated Graph API evidence, not browser claims or inferred access.
Skip registration/deregistration for coexistence numbers.

## Remaining implementation (release blockers)

- Confirm Tech Provider/advanced access state in Meta. Business verification
  alone does not establish approval. Review current Embedded Signup configuration
  version; v2 is deprecated 2026-10-15 according to the primary source.
- Bind selected mode to the server-side one-use signup state. Keep tenant,
  admin and session binding. Never accept a different mode at completion.
- Launch the documented business-app flow, handle its distinct completion event,
  cancel/error, timeout and listener cleanup. Obtain the code and verified asset
  ownership, resolving missing IDs without trusting an arbitrary tenant claim.
- Subscribe WABA and app fields: messages, history, smb_app_state_sync,
  smb_message_echoes and account_update. Verify signed webhook ingress.
- Persist synchronization jobs before requesting contacts/history. The official
  sync window is 24 hours. Each request can be performed only once: store request
  IDs and treat ambiguous network outcomes as reconciliation, not blind retries.
- Ingest history and contact updates idempotently with tenant isolation. Handle
  history refusal 2593109, chunk progress and media placeholders. Never enqueue
  imported history as new customer input or extend the API service window.
- Persist mobile message echoes in conversation history as outbound human
  messages, deduplicate them and atomically pause AI. Cancel queued AI replies
  and recheck control state immediately before dispatch. In-flight requests
  cannot be recalled: describe that residual race honestly.
- Add explicit human resume action and audit event. Test interaction with
  greetings/away messages and repeated/delayed echo deliveries.
- Handle PARTNER_REMOVED and stop sends after disconnection; never deregister
  an existing business-app number. Show clear reconnect/pending states.
- Verify a pilot end to end: inbound, agent outbound, mobile outbound/AI pause,
  explicit resume, history refusal, duplicate/reordered delivery, tenant isolation,
  connection loss and preservation of mobile access.

## Customer-facing constraints

Existing WhatsApp Business app required. No guarantee of immediate eligibility.
Cloud API prices and service windows still apply on the API side. App messages
do not extend the API service window. Avoid claiming full feature parity:
groups/calls/catalog/labels are not synchronized through this flow; disappearing,
view-once, live location and broadcast-list behavior changes. Explain companion
device relinking and consent before activation. No automatic fallback to API_ONLY.
