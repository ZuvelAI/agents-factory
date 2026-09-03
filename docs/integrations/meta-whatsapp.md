# Meta WhatsApp Cloud API

Authentication uses Meta Embedded Signup and stores only an encrypted token
reference. The backend verifies webhook signatures before parsing, deduplicates
provider event IDs, preserves per-conversation ordering and sends text responses
through the durable outbox. Coexistence is enabled only when the account is
eligible and its operating handoff is configured.

Required scopes and account mappings are selected by the approved Meta signup
flow. Supported v1 operations are inbound message receipt, text reply, approved
template send, delivery status, health, reconnect and revoke. Unsupported media
analysis or voice response remains unavailable.

Stable errors include invalid signature, duplicate event, account disconnected,
template not approved, provider unavailable and uncertain send. A retry never
asserts success without provider evidence and idempotency prevents consequential
duplicates. See [reconnect](../operations/reconnect.md) and
[incident response](../operations/incident-response.md).
