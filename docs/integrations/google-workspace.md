# Google Workspace primitives — Task 23

Task 25 adds nine order-domain operations to the Sheets catalog, selected through
`OrdersSheetResource` and its derived per-binding operation set. The original 11
native primitives below remain available. See `google-sheets-orders.md` for the
order mapping, connection-level serialization and receipt/reconciliation contract.

Native backend adapters, following the approved v1 plan. Codex's use of MCP tools
does not change product integrations into MCP. No Google Contacts, Gmail inbox
reading, Generic REST, public file sharing or business capability tools are added.

## Configuration and connection

`GOOGLE_OAUTH_CLIENTS` is an optional, backend-only secret JSON map. Keys may be
`google_calendar`, `gmail`, `google_drive`, `google_sheets`. Each configured product
has `client_id`, `client_secret`, and a fixed HTTPS `redirect_uri`. Supply actual
values through the deployment secret manager/local ignored environment; never
commit them. An absent map leaves Google unavailable. Invalid maps fail startup
with a sanitized configuration error. No credentials were provisioned by Task 23.

Register redirect URIs in the corresponding Google Cloud OAuth client and enable
the needed product APIs. Use the existing platform-admin `/integrations/oauth/start`
and `/oauth/callback` lifecycle (see connection lifecycle documentation). Offline
authorization uses consent + PKCE, state bound to tenant/admin/session, and exact
requested/granted scope equality. Reconnect if Google does not issue the refresh
credential required for unattended operation. Token payloads are encrypted by the
existing SecretVault, not stored in AgentSpec, operation arguments or logs.

Scope names below have the prefix `https://www.googleapis.com/auth/`:

| Product | Declared operations | Accepted scope(s) |
| --- | --- | --- |
| Calendar | `calendar.check_availability` | `calendar.events.freebusy` |
| Calendar | `calendar.list_events`, `calendar.get_event` | `calendar.events.readonly` OR `calendar.events` |
| Calendar | `calendar.create_event`, `calendar.reschedule_event` | `calendar.events` |
| Gmail | `gmail.send_approval_notice` | `gmail.send` only |
| Drive | `drive.read_file`, `drive.store_evidence` | `drive.file` only |
| Sheets | `sheets.read_rows` | `spreadsheets.readonly` OR `spreadsheets` |
| Sheets | `sheets.append_row`, `sheets.update_row` | `spreadsheets` |

An appointments binding with availability and writes requests both Calendar write
and free/busy scopes, not blanket Calendar access. Never request every allowed
scope by default. Drive file IDs/folders must be explicitly authorized for the app
(created by the app or selected/shared through Google's per-file authorization);
knowing an ID alone does not grant `drive.file` access. Picker/onboarding UI is not
implemented in this primitives task. Google consent verification and actual account
authorization are deployment/onboarding prerequisites, not claimed complete here.

## Backend execution boundary

`ConnectedGoogleConnector` is trusted backend composition: tenant/binding ID,
connection ID, operation allowlist and a typed product resource configuration.
It holds no decrypted tokens. `IntegrationService.execute_connector` resolves
SecretRef only for identified backend system/platform-admin actors (job/action ID
for workers; no anonymous actor), locks the connection
against refresh/revoke, refreshes near-expiry credentials, and records sanitized
operation outcomes in the audit log. There is no generic HTTP execute endpoint.
Callbacks/resources are code-owned, never supplied by the model. Future capability
packs must invoke this boundary **after** existing identity, risk, confirmation,
approval and action-idempotency checks; connector scope checks do not replace them.

Runtime tool visibility still depends on Capability/AgentSpec bindings. A manifest
being AVAILABLE means its code exists, not that any tenant can execute it without
a configured provider, a healthy connection and an approved resource binding.

All adapters return `ConnectorResult` with selected fields. Logs contain only
connector/operation, tenant/binding, duration, outcome and safe error codes. Provider
diagnostics, request bodies, resource contents and credentials are not logged.
The fixed-origin HTTP transport disables redirects and automatic retries, bounds
response bytes and applies network timeouts. OAuth tokeninfo uses the POST/query
form in Google's discovery document via the transport directly, avoiding the HTTP
client's URL logger; do not add raw request/URL logging to this boundary.

## Resource contracts and safety limits

- Calendar: configured calendar ID only; timezone-aware timestamps plus an IANA
  timezone; windows up to 31 days. Lists follow page tokens with a 20-page ceiling,
  reject repeated tokens and never report truncated data as complete. Free/busy
  errors mean availability unknown, not empty occupancy. Creates use a deterministic
  provider event ID and request digest; a duplicate ID is reconciled, not blindly
  re-created. Reschedules use `If-Match` and return `stale_version` on a changed event.
- Gmail: configured sender and approved recipient allowlist, plain-text approval
  notices only. Provider IDs are returned. A deterministic Message-ID aids
  reconciliation but **does not** promise Gmail deduplication.
- Drive: configured evidence folder and explicit readable file IDs. Reads return
  base64 content plus file metadata/provenance. PDF/plain text/CSV/JPEG/PNG allowed,
  at most 10 MiB (a binding can lower this). Native Google Docs export to plain text;
  Sheets export to CSV. Metadata size and streamed bytes are both checked. Uploads
  do not create public permissions; the configured folder's ACL still applies.
- Sheets: configured spreadsheet/tab, exact ordered headers and domain-field map.
  Header drift blocks all operations. Reads use bounded row windows (up to 500 per
  call), returning physical row numbers and `next_row`. Writes use RAW cell input;
  formulas supplied as text are not executed. Updates require the expected full
  mapped row and change only targeted cells, preserving other cells/formulas.
  `max_rows` bounds read/range scans, not Google append's resulting table capacity.

Sheets has **no atomic compare-and-swap** with this API. The precondition check is
not a transaction against concurrent human edits. Task 25 must add action-level
serialization/reconciliation and explicit uncertain outcomes; do not promise
database-grade atomicity. Similarly, Gmail sends, Drive uploads and Sheets appends
need the existing durable Action layer to prevent duplicate submissions. These
adapters never automatically replay writes after timeout/5xx: outcome is UNCERTAIN.
Provider 401/revocation, denied permissions, missing resource, 429, stale versions
and transient failures map to safe codes; there are no invented success responses.

## Health and isolation

Health checks verify token audience, expiry and exact scopes without reading the
Gmail inbox or adding profile permissions. They measure authorization health;
resource-specific permission/API availability is checked by each operation.
Separate local connection records isolate outages/revocation state. **Google may
revoke a combined authorization across scopes/clients in the same Cloud project**.
Use genuinely independent grants/projects when provider-level isolation is needed;
different local IDs alone cannot guarantee this. No code silently widens scopes.

## Focused verification

Provider contract tests cover all 11 advertised operations using sanitized,
synthetic fixtures shaped from the official APIs (not live customer recordings).
One database integration scenario covers real encrypted connection resolution,
renewal before execution, audit redaction, backend/tenant gating and independent
Google connection health. No live account authorization is claimed. Old milestone
suites and full CI need not be rerun for this checkpoint.

## Primary API references

- [OAuth web-server authorization](https://developers.google.com/identity/protocols/oauth2/web-server)
- [OAuth tokeninfo discovery](https://www.googleapis.com/discovery/v1/apis/oauth2/v2/rest)
- [Calendar free/busy](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query)
- [Calendar event insertion](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)
- [Gmail message sending](https://developers.google.com/workspace/gmail/api/guides/sending)
- [Drive per-file authorization](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Sheets values API](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values)
- [Google cross-client authorization](https://developers.google.com/identity/protocols/oauth2/cross-client-identity)
