# Coexistence implementation ledger

Approved scope: conversation plan approved 2026-09-23. Base: 4e85b3d.
Branch: codex/whatsapp-coexistence. No deployment or live-number onboarding authorized.

## Work sequence

1. Bind one-use signup state to the selected mode; reject mode substitution.
2. Implement verified coexistence authorization and its distinct browser callback.
3. Persist and ingest history, contacts, mobile echoes, and disconnection events.
4. Pause AI on mobile replies, cancel pending sends, guard dispatch, explicit audited resume.
5. Add tenant-isolated status/control UI and durable synchronization orchestration.
6. Run isolated tests and security review; present deployment/pilot readiness separately.

## Constraints

- Keep the release gate closed until all stages pass.
- Never register/deregister an existing Business app number or fall back to API_ONLY.
- Never run tests against the configured production database or start existing workers.
- Use independent test dependencies and a disposable database without real credentials.
- Preserve the checkpoint and other working directories.
- User direction 2026-09-25: preserve Meta reviewer account for future reviews;
  defer its internal correction until the end. Customer demo is out of scope and
  deferred until separately requested. Do not change credentials or reviewer access.

## Progress

- Isolated worktree created from the checkpoint; branch created.
- Official Meta coexistence documentation retrieved on 2026-09-23. It confirms a
  distinct completion event, server-side asset resolution, one-shot contacts/history
  synchronization, and mobile echo events. Recheck version-4 launch requirements.
- Isolated test image and pinned development dependencies are ready. Tests run
  without network access or production credentials. A separate disposable database
  has the migrations applied; no production migrations have been applied.
- Signup state now binds the selected mode in the service and database query.
  Contract tests passed after first observing failures. Eleven real-database tests
  now pass: mode/tenant/admin/session binding, expiry boundary, replay, concurrent
  consumption and consumption surviving a callback transaction rollback.
- User authorized resolving baseline scanner false positives on 2026-09-24.
  Renamed runtime credential variables and used destructuring for login form values;
  scanner rules and exclusions are unchanged. Added disposable-repository tests
  proving that literal tokens, passwords, client secrets and private-key headers
  remain blocked, and an innocuous repository passes.
- Server-side authorization now resolves omitted business/phone IDs from Meta.
  Ambiguous or paginated phone selections fail closed. Coexistence requires exact
  phone identity plus boolean is_on_biz_app=true and platform_type=CLOUD_API;
  missing/malformed evidence stays UNKNOWN. New provider cases observed RED/GREEN.
- Browser parser accepts the coexistence-specific completion event with WABA-only
  data, rejects mode substitution and untrusted origins, and preserves API_ONLY
  required fields. Frontend/backend release gates remain CLOSED.
- Latest verification (2026-09-24): 274 backend unit/contract tests passed; 23
  frontend unit tests passed; frontend tsc --noEmit --incremental false passed;
  47 integration tests passed. test_database_gate_removes_stale_schema_state failed
  because isolated image lacks pnpm (environment reset test, not application code).
  Redis conversation-lock tests were excluded; full environment/security DB gates
  remain pending. git diff --check and focused Ruff F checks passed.
- Focused security suite: 65 passed against the disposable database (tenant
  isolation matrix and secret-tenant-isolation suites not included). Initial run
  lacked TEST_DATABASE_URL for human_active_silence; rerun with isolated URL passed.
- Next: version-4 launch options and cancellation/listener cleanup; durable sync
  records and ingestion of history/contacts/mobile echoes; human takeover and
  outbound race protection. No live Meta scripts executed, number connected,
  deployment performed or production migration applied.
- Ruling: use this durable ledger for the conversation-approved plan instead of
  task-script briefs (no machine-formatted plan exists). No scope change.

## Mobile takeover checkpoint — 2026-09-24 (stages 3/4 still in progress)

- Signed smb_message_echoes are parsed separately from customer input. Mobile
  replies persist as human outbound messages, deduplicate, and move new/AI/
  awaiting-human/closed conversations to HUMAN_ACTIVE without queuing an AI turn.
- PREPARED AI replies for that conversation become BLOCKED atomically with
  takeover. RED observed PREPARED instead of BLOCKED; GREEN verified persisted
  status and zero provider dispatches. Already dispatched outcomes are preserved.
- Dispatch and mobile takeover share a conversation-specific advisory fence;
  conversation rows lock before outbound rows. Concurrency regression first
  failed because takeover committed during the paused provider call, then passed.
- Pool-size-one regression exposed nested-connection exhaustion. Dispatch now
  reserves one connection across separately committed claim/result transactions,
  with a session fence and connection invalidation on interruption. Regression
  passed; cancellation test confirms fence release and UNCERTAIN (no re-send).
- Ruling: preserve the result of a provider call already in flight, serializing
  committed mobile takeover behind it — sent messages cannot be recalled, and
  pretending they were cancelled risks duplicate sends. Cost: takeover may wait
  for the bounded provider call; delivery preceding webhook arrival is unavoidable.
- Fresh verification: 278 unit/contract tests passed; 56 integration tests passed
  against disposable PostgreSQL. Integration excludes test_database_gates.py and
  test_conversation_lock.py (same unavailable pnpm/Redis gates, not waived).
  Focused Ruff F check passed with --no-cache; initial read-only-cache run could
  not create its cache. No full-suite or release-readiness claim.
- Next safety work: batched/concurrent multi-conversation lock ordering, tenant/
  account rejection coverage, media echo preservation, delayed/replayed echo
  semantics, direct/session database connection requirement for advisory fences
  (transaction-pooling compatibility not validated). Keep release gate CLOSED.
- Remaining planned work: history/contacts/disconnect ingestion and one-shot sync,
  explicit audited resume and UI, SDK v4/cancellation cleanup, complete security
  gates and fresh whole-branch review. No production services or real number touched.

## Contacts, batch isolation, signup lifetime — 2026-09-25

- Fixed multi-conversation deadlocks by acquiring every affected conversation
  fence in sorted order before webhook writes (inbound, status, mobile, contacts).
  Reversed-batch concurrent regression observed lock timeout before the fix.
- Mobile echo writes require the exact active coexistence WABA/phone/account and
  tenant. Added rejection, signature, cross-tenant duplicate-ID and media coverage;
  non-text image/audio/video/document/location/contacts payloads are preserved.
- Added signed smb_app_state_sync contact normalization and tenant-isolated
  whatsapp_contacts persistence. Migration created with Supabase CLI and applied
  only to disposable databases. Add/update/remove events never queue AI work;
  duplicate/stale events do not overwrite newer data, equal-time removal wins and
  clears names. Parser and storage tests observed RED then GREEN (5 + 4 cases).
- Registered contacts and the previously unregistered tenant_onboarding_configs
  in the full tenant attack matrix. Row-key support accommodates its tenant_id PK;
  application writes remain denied. No database permissions relaxed.
- Created isolated security PostgreSQL/Redis containers, without exposed ports or
  persistent volumes, using test-only credentials. Fresh matrix + secret isolation
  suite: 27 passed. Fresh whole backend suite: 457 passed, 2 failed, no setup errors.
  Failures retained, not waived:
  * test_core_contains_no_customer_uuid_or_tenant_id_conditionals: baseline
    review_router.py and review-access.ts contain fixed customer UUIDs. This is
    an intentional restricted reviewer surface; changing authorization requires
    a separate decision, not a weakened scanner or removed access guard.
  * test_database_gate_removes_stale_schema_state: pnpm 11.24.0 unavailable in
    test image. Do not run reset script against the existing local stack. Test
    leaves only its empty marker table in the disposable security database.
- Signup code/assets now settle together with a bounded timeout and cleanup on
  success, SDK failure, cancellation or component unmount. Late callbacks cannot
  complete a cancelled attempt. Begin failures are caught and duplicate clicks
  blocked synchronously. Seven new lifecycle tests observed RED then GREEN;
  full frontend unit suite 30 passed, TypeScript check passed.
- Official Meta version-4 documentation retrieved directly on 2026-09-25:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/version-4
  Product selection in Facebook Login for Business configuration controls v4;
  it is NOT the sessionInfoVersion field. Retained sessionInfoVersion=3 and added
  the coexistence-only featureType selector. Existing remote configuration is
  not independently verified or changed. Release gate remains CLOSED.
- Ruling: expand the security registry rather than excluding preexisting onboarding
  data — all tenant-owned tables must face the same attacks; cost is maintaining
  row-key-aware test helpers. No production behavior change for that table.
- Remaining: SDK script-load failure/abort lifecycle, browser-level verification,
  durable one-shot synchronization/history/disconnect, delayed echo/resume rules,
  tenant status controls, direct/session connection enforcement, baseline gates,
  final whole-branch review. This is a checkpoint, not release readiness.

## History normalization checkpoint — 2026-09-25

- Added a distinct history_sync contract, separate from inbound messages, mobile
  echoes and live delivery statuses. Preserves chunk metadata, threads, historical
  message content, media placeholders and subsequent history-field media messages.
- History-sharing denial (2593109) remains an explicit sync error payload, not
  an empty successful import. Validates phase/chunk/progress and timestamps.
- Seven contract tests failed before implementation and passed afterward; full
  unit/contract suite: 302 passed. Full backend suite: 464 passed, 2 failed.
  Existing failures remain test_core_contains_no_customer_uuid_or_tenant_id_conditionals
  (review surface deferred by user) and test_database_gate_removes_stale_schema_state
  (marker left by prior failed reset; pnpm/reset environment still unavailable).
- This checkpoint ONLY normalizes history. Durable history inbox, async import,
  deduplication and progress tracking remain pending; do not enable coexistence or
  history subscriptions on its basis. Current processor does not persist history
  batches yet. Release gate remains CLOSED, no Meta account/configuration changed.

## Durable history inbox checkpoint — 2026-09-25

- Signed history batches now persist in the webhook transaction before acknowledgement.
  Canonical SHA-256 payload deduplication is scoped to tenant and WhatsApp account.
  Chunks and delayed media remain separate from the live-message pipeline: no AI
  job, conversation or customer messaging window is created by this ingestion.
- Added append-only inbox with forced RLS, explicit select/insert grants and a
  composite tenant/account foreign key. Registered the table in the full tenant
  isolation attack matrix, including cross-tenant parent attacks.
- Guard requires matching tenant, WABA, phone and active COEXISTENCE account.
  Deliberately does not grant UPDATE on accounts just to acquire a row lock.
  Disconnect serialization/revalidation remains part of the pending importer work.
- CLI-generated migration applied ONLY to disposable isolated security database.
  Regression observed missing table, then zero stored rows before implementation.
  Fresh targeted verification: 249 passed (unit, history integration and full
  tenant isolation matrix). Full backend/release suite has NOT been rerun here;
  previously documented baseline failures remain unresolved.
- Next: asynchronous historical import, progress/error handling, one-shot sync and
  disconnect handling. Inbox storage is not yet user-visible imported history.
  Release gate stays CLOSED. Meta reviewer account, pilot number and production
  are unchanged; reviewer correction stays deferred until the end per user.

## Historical archive checkpoint — 2026-09-26

- Added a validated archive projection for chunk order/progress, incoming and
  business messages, provider ID deduplication, and explicit history-sharing
  denial. Unmatched delayed media stays pending; it is never silently marked
  imported. Five projection tests observed RED before implementation, then GREEN.
- A new CLI-generated migration adds a separate tenant-isolated historical
  message archive and per-inbox import receipts. Imported history never enters
  live conversations/messages/outbox and therefore cannot start an AI turn or
  messaging window. Matching replay returns zero new imports; provider-ID
  conflicts are rejected. Cross-tenant RLS and composite foreign keys apply.
- The import function exists but no background worker schedules it yet. Media
  reconciliation, one-shot synchronization and disconnect handling still block
  rollout. The migration was applied only to the disposable security database.
- Fresh verification: 29 tenant attack-matrix cases passed; 4 archive integration
  cases passed; Ruff F check passed. Full backend: 481 passed, 2 previously known
  failures (deferred Meta reviewer hardcoding and isolated database reset marker).
  No production database or Meta configuration changed; release gate CLOSED.

## One-shot sync request checkpoint — 2026-09-26

- Added the documented Meta SMB App Data request for contacts and history,
  validating its `request_id`; contract tests observed RED/GREEN with an
  isolated HTTP transport. No real Meta request has been made.
- New durable, tenant-isolated request record reserves each sync type once per
  eligible coexistence account. The reservation commits before HTTP. An
  ambiguous outcome remains UNKNOWN and is not automatically retried. Meta's
  accepted request ID is retained for support. New requests require the
  verified signup timestamp to be within the 24-hour window.
- The one-shot coordinator is not yet wired to the onboarding flow or a worker;
  account token resolution, UI status, webhook completion and support handling
  remain. The production gate is still CLOSED. Ruling: UNKNOWN is a manual
  reconciliation state, because repeating Meta's one-time call after a timeout
  could violate its documented once-only rule. Cost if wrong: a legitimately
  unsent request needs support/manual review before the 24-hour window closes.
- Migration applied only to disposable security DB. Fresh verification: 33
  focused integration/security tests and 3 Meta contract tests passed; Ruff F
  passed; full backend 488 passed with the same two known failures (deferred
  reviewer-account conditional and test DB reset marker).

## Delayed historical media checkpoint — 2026-09-26

- Historical media arriving before its archived placeholder now remains pending
  without a success receipt. Once the original chunk arrives, importing the
  media batch fills that archived placeholder by provider message ID and
  validates sender and timestamp. The live conversation/AI path is untouched.
- A migration grants only content updates on archived messages, with a tenant
  RLS policy and a trigger allowing only placeholder-to-media transitions while
  preserving the provider message ID. Repeat overwrites are rejected.
- RED observed an unsupported-media exception; GREEN verified media-before-
  placeholder, reconciliation, two receipts, zero live messages/conversations/
  AI jobs, and rejection of a later overwrite. Security matrix: 30 passed.
- Fresh full backend: 489 passed, same two known failures only. Ruff F passed.
  Worker scheduling/retry of pending local inboxes remains to be connected;
  release gate CLOSED and pilot/Meta reviewer unchanged.

## Asynchronous history importer checkpoint — 2026-09-26

- Signed, deduplicated history webhook batches now enqueue exactly one
  `whatsapp.history.import` outbox job in the same transaction as the inbox row.
  The scheduler routes it to a dedicated archive handler, separate from the
  live inbound/agent-turn handlers. Duplicate webhooks create no extra job.
- The worker validates tenant, job payload, inbox and account identity before
  importing. A media-only batch that arrives first stays without a receipt;
  subsequent chunk import revisits eligible pending media batches in the same
  tenant/account until reconciled. No live conversation/message or AI turn is
  created. This is local replay, not a repeated one-shot Meta sync request.
- RED observed missing archive job and missing worker handler. GREEN verified
  deduplication, repeat worker delivery, media-before-chunk reconciliation and
  zero live/AI side effects. Fresh focused tests: 12 passed. Fresh full backend:
  491 passed, the same two existing failures (deferred reviewer-account
  conditional and stale marker in disposable DB). Ruff F passed.
- Still pending: wire one-shot sync to verified onboarding/token resolution,
  status and disconnect controls, delayed echo/resume policy, browser flow,
  final security review and rollout gates. No Meta request, pilot onboarding,
  production deployment or reviewer-account changes. Release gate CLOSED.

## Onboarding-to-one-shot sync checkpoint — 2026-09-26

- Eligible coexistence signup now schedules separate contact and history sync
  outbox jobs in the same database transaction as the connected account. The
  scheduler routes them to the outbound worker. An API-only account cannot
  schedule coexistence sync, duplicate scheduling creates no extra jobs, and
  queue payloads contain account/type identifiers but never credentials.
- The worker validates the tenant-scoped job, resolves the account-bound secret
  in a short app-role transaction, then invokes the prior one-shot coordinator.
  A durable UNKNOWN reservation commits before the provider call, so uncertain
  results and repeated jobs never send again. An accepted replay can finish
  without rereading a credential that may since have been revoked.
- Ruling: keep the existing COEXISTENCE signup release gate closed while this
  code is integrated — sync lifecycle/status, disconnect, browser verification
  and final security review remain incomplete. Cost if wrong: a newly connected
  client would not yet be able to use coexistence; no existing client or pilot
  number is modified by this branch.
- RED observed missing queue scheduling, missing worker and replay credential
  access. GREEN focused tests: 6 sync integration tests. Missing Graph endpoint
  now raises a sanitized configuration error before any HTTP call. Fresh full
  backend: 495 passed, the same two existing failures (deferred Meta reviewer
  conditional and stale disposable-DB marker). Ruff F and targeted mypy passed.
  No live Meta request, production deployment or reviewer-account change.

## Sync request visibility checkpoint — 2026-09-26

- Added a read-only, platform-admin-only sync-status endpoint scoped to the
  selected tenant and coexistence account. It reports each one-shot type as
  NOT_REQUESTED, UNKNOWN, or ACCEPTED, with Meta's support request ID only
  when accepted. A foreign-tenant/account lookup returns 404. No tokens appear.
- Ruling: ACCEPTED means Meta accepted the request, not that all asynchronous
  contacts/history were delivered or imported — the endpoint intentionally
  does not claim completion. Cost if wrong: operators must inspect webhook
  receipts separately until a completion model is added.
- RED observed absent status reader and route; GREEN focused sync suite: 8
  passed. Full backend after implementation: 497 passed, same two existing
  failures. Ruff F and targeted mypy passed. Release gate remains CLOSED.

## Persisted sync evidence checkpoint — 2026-09-26

- Added a separate platform-admin-only observation endpoint for one coexistence
  account. It counts active imported contacts and received, imported, declined,
  or locally pending history batches, scoped to that tenant/account. A foreign
  account returns 404. No personal contact data or credentials appear.
- These are locally persisted counts, not Meta delivery totals or a completion
  signal. An accepted one-shot request with zero received batches remains
  ambiguous; the release gate is still CLOSED.
- RED observed the missing reader after correcting a test-fixture collision on
  Meta's globally unique phone ID. GREEN focused sync suite: 9 passed. Ruff F
  and targeted mypy passed. Full backend: 498 passed, same two known failures
  (deferred Meta reviewer conditional and stale marker in the isolated database).
  No live Meta activity, reviewer-account change, or production deployment.

## Verified display-number identity checkpoint — 2026-09-26

- Meta's documented PARTNER_REMOVED account_update identifies the displayed
  business phone number rather than AI Workers' stored phone-number ID. The
  signup provider now fetches the display number with the exact selected
  phone ID, normalizes it to ASCII digits, and refuses COEXISTENCE signup if
  the verified identity is absent or malformed. API_ONLY remains compatible.
- Added a constrained nullable account column and an active-coexistence
  WABA/display-number uniqueness index. The account repository persists the
  verified digits on insert and reconnection. Existing accounts remain NULL;
  no inference is made from phone IDs or customer messages.
- RED observed the missing provider field, the missing service refusal and
  repository argument, wrong-ID identity acceptance, and absent DB column.
  GREEN: provider contract, service contract and real-database persistence.
- Ruling: do not map a disconnect by WABA alone when its phone number cannot
  be matched exactly — a WABA may contain several phones. Cost if wrong:
  unmatched disconnects must remain pending for investigation rather than
  immediately suppressing one account; keep release gate CLOSED until an
  event handling strategy is implemented and tested.
- Ruling: Supabase CLI is unavailable in this isolated worktree (the available
  pnpm version is incompatible and the checkout's optional CLI binary is
  missing), so the migration file was added in the repository's established
  format and applied with psql ONLY to the disposable test container. Cost if
  wrong: migration metadata/format needs confirmation in final review before
  production use. No remote Supabase project or production schema was changed.
- Full backend regression: 500 passed, the same two known failures (deferred
  reviewer-account conditional and stale isolated-DB marker). Ruff F and
  targeted mypy passed. Account_update parsing/quarantine is NOT yet wired;
  the release gate stays CLOSED. No live Meta request or Zuvel number change.

## Exact-number Meta disconnect checkpoint — 2026-09-26

- Added typed `account_update` parsing, including Meta's entry timestamp and
  normalized display phone. `PARTNER_REMOVED` without a valid phone or event
  time is rejected. After signature verification, a private database function
  atomically deactivates only the active COEXISTENCE account matching both
  WABA and verified display phone. Replayed events are harmless; events older
  than the current registration do not deactivate it. No credential is exposed
  or automatically revoked; inactive status blocks subsequent outbound work.
- Ruling: WABA-only `ACCOUNT_OFFBOARDED` and `ACCOUNT_RECONNECTED`, other
  account-update types, and unmatched `PARTNER_REMOVED` return a retryable 503
  rather than silently acknowledging or changing an unrelated account.
  `ACCOUNT_RECONNECTED` never automatically reactivates an account. Cost if
  wrong: Meta may retry these ambiguous events repeatedly and an operator
  still lacks a durable quarantine/alert queue. This must be resolved and
  tested before the COEXISTENCE release gate opens.
- RED observed unsupported `account_update` and silent processing. GREEN:
  parser and real-database integration tests for exact match, replay, stale
  registration, WABA isolation and ambiguous updates (21 focused tests).
  Full backend: 508 passed, the same two existing failures (deferred reviewer
  account conditional and stale disposable-DB marker). Two temporary security
  test failures were caused by a synthetic test fixture named `SECRET`; the
  fixture was renamed without changing the security detector, and those tests
  now pass. Ruff F and targeted mypy pass. The migration was applied only to
  the disposable local PostgreSQL container. No live Meta call, account
  change, production deployment or reviewer-account correction.

## Ambiguous account-update quarantine checkpoint — 2026-09-26

- Signed account-update events that cannot safely identify one active number
  now enter a private, durable, deduplicated alert table before the webhook
  acknowledges them. This covers unmatched or unverified PARTNER_REMOVED and
  WABA-wide/unsupported events such as ACCOUNT_OFFBOARDED and
  ACCOUNT_RECONNECTED. Replays create one alert; invalid signatures create none.
  Exact verified PARTNER_REMOVED handling remains unchanged.
- The webhook role has INSERT only; public roles cannot read or write the table.
  A new bounded read-only platform-admin route lists alert metadata for manual
  investigation, not a client/tenant route and not an automatic resolution.
  Missing authentication returns 401; a principal without DB membership gets
  403. No token, raw payload, or secret is returned.
- Ruling: acknowledge only after the alert transaction commits; unexpected
  persistence failure still yields a retryable error. Never infer a phone from
  WABA alone or automatically reactivate on ACCOUNT_RECONNECTED. Cost if wrong:
  an operator must review an alert instead of the app making a potentially
  destructive guess. Operational alert notification/resolution is still pending.
- RED observed absent queue and absent admin route; GREEN focused real-database
  suite: 8 passed. Full backend: 514 passed, same two known failures (deferred
  Meta reviewer conditional and stale marker in isolated test DB). Targeted
  Ruff lint, format and mypy pass. The migration was applied only to disposable
  local PostgreSQL; no remote/project schema, live Meta number, credentials,
  reviewer access, or production deployment changed. Release gate remains CLOSED.

## Meta SDK loading lifetime checkpoint — 2026-09-27

- The existing click-to-connect browser flow now passes its attempt's abort
  signal into a bounded Meta SDK loader. A failed script can be retried; a
  script that never loads times out after 15 seconds; cancellation removes an
  unshared script and clears listeners/timers. If two attempts are waiting on
  the same script, cancelling either one preserves the other's load.
- Ruling: retain on-demand script insertion for this SDK because loading is
  initiated by a user attempt and must share that attempt's cancellation and
  retry lifecycle. Cost if wrong: this bypasses Next's generic script manager;
  browser-level verification of the actual Meta script remains necessary.
- RED: absent loader behavior, then both shared-cancellation cases failed
  before the fix. GREEN: 5 focused loader tests; full control-plane unit suite
  35 passed, TypeScript check and targeted ESLint/Prettier passed. Browser E2E
  against Meta was not run. The COEXISTENCE signup gate remains CLOSED; no
  live number, reviewer account, remote Meta setting, or production deployment
  changed.

## Admin sync visibility and local browser checkpoint — 2026-09-27

- With disposable local authentication and no backend or live Meta connection,
  the WhatsApp page showed the coexistence option, its pending-habilitation
  warning and a disabled Meta connection button. No credential fields were
  exposed. The first browser pass showed no console errors. A later reload
  lost the fake session because the disposable auth server does not implement
  token refresh; it returned to login and logged `AuthApiError: not_found`.
  This does not validate a connected-account browser flow.
- The platform-admin account page now reads existing per-account one-shot
  request status and persisted observations for COEXISTENCE accounts only.
  It distinguishes NOT_REQUESTED, UNKNOWN/manual review and ACCEPTED; lists
  local contact/history counts; and explicitly says Meta acceptance or local
  counts do not prove synchronization completion. It does not show request IDs,
  credentials or contact details. Incomplete/malformed responses show an
  unavailable notice instead of an apparently complete report.
- Ruling: keep this view read-only and never label accepted requests as
  completed — Meta's asynchronous delivery has no completion evidence here.
  Cost if wrong: administrators must investigate delivery outside this view
  until a durable completion model and end-to-end test exist.
- RED observed missing display, then omitted-status and partial-count
  regressions; GREEN 4 focused tests. Fresh full control-plane unit suite:
  39 passed. TypeScript, targeted ESLint, Prettier and diff check pass.
  Connected-account browser E2E and backend/full-branch security gates remain
  pending. Release gate CLOSED; no live Meta request, Zuvel number onboarding,
  reviewer-account edit, production deployment or migration.

## Explicit return from mobile human control — 2026-09-27

- Added an admin-only route for one conversation on one WhatsApp account to
  return from HUMAN_ACTIVE to AI_ACTIVE with an expected state version. The
  route rejects a wrong account, stale version, inactive/API_ONLY/ineligible
  account and missing administrator credentials. It records the identified
  administrator and reason in the state-event and audit trail; it does not
  generate an AI reply merely by resuming control.
- The database transition obtains the same per-conversation dispatch fence as
  mobile echoes/outbound delivery, then rechecks the active eligible account
  under row locks. A direct application-role call that spoofs a platform-admin
  actor is rejected. RED was observed for the absent route and this spoofed
  transition; GREEN after the implementation.
- Focused state/route/security tests: 23 passed. Related conversation,
  takeover and outbound integration tests: 33 passed. Backend unit suite:
  225 passed. Targeted Ruff lint/format and mypy passed; diff check passed.
  A new migration was applied only to disposable local PostgreSQL.
- This is an API checkpoint, not a complete operator workflow. A conversation
  list/control UI, concurrent operator/browser verification, full-branch
  security gates and the previously recorded environment/reviewer-account
  baseline issues remain. Release gate CLOSED. No live Meta call, Zuvel
  number onboarding, reviewer-account change or production deployment.

## Human-control operator view — 2026-09-27

- Added a platform-admin-only, account-scoped list of up to 20 recent
  HUMAN_ACTIVE conversations for active, eligible COEXISTENCE accounts. It
  exposes only the conversation UUID, masked final four customer digits and
  state version. Wrong tenant/account and inactive accounts fail closed.
- The WhatsApp administration page distinguishes an empty list from a failed
  lookup, never displays the full customer ID and requires an explicit
  confirmation to return one conversation to AI. The action sends the visible
  version to the guarded resume route, reports stale state separately, and
  does not send an immediate AI message.
- RED/GREEN tests cover account/tenant isolation, masking, malformed response
  rejection, confirmation, exact request and conflict handling. Fresh checks:
  46 control-plane unit tests, TypeScript, ESLint and Prettier passed; 34
  related database integration tests passed; 96 security tests passed with a
  disposable test-only master key; targeted Ruff and mypy passed. The broad
  supported backend matrix yielded 523 passes and one pre-existing architecture
  failure for the deferred Meta reviewer-account conditional.
- A follow-up real-database race test started two administrator sessions
  together against the same human conversation and same expected version.
  Exactly one resume succeeded, the other received 409, and only one audited
  state event was created. The test passed; the refreshed broad matrix yielded
  524 passes and the same pre-existing architecture failure. Ruff lint/format
  of the follow-up test passed.
- The complete backend matrix remains unverified: its initial collection
  failed because the isolated offline image lacks `arq`. The broad matrix
  therefore excluded the outbox-dispatch module, Redis conversation-lock
  tests and database reset gates. Browser E2E and concurrent browser-request
  verification remain pending. Release gate CLOSED; no live Meta call, Zuvel
  number onboarding, reviewer-account change or production deployment.

## Isolated gate recheck — 2026-09-27

- Confirmed the already-running disposable Redis container shares the
  disposable PostgreSQL network namespace. Its two conversation-lock tests
  passed. Installed the lockfile-pinned `arq` test dependency in the isolated
  worktree environment, allowing the outbox-dispatch module to be collected.
- Fresh backend run with disposable PostgreSQL, Redis and a test-only key:
  528 passed, one pre-existing architecture failure in the deferred Meta
  reviewer-account conditionals. Fresh control-plane run: 46 unit tests and
  TypeScript passed. No production services or Meta settings were changed.
- Ruling: do not run `test_database_gate_removes_stale_schema_state` here —
  its reset script invokes the local Supabase CLI and could reset the active
  local stack, not just the disposable test database. Cost if wrong: that
  database-reset gate remains unverified until it has a dedicated isolated
  Supabase instance. Browser E2E also remains pending. Release gate CLOSED.

## Verified phone identity in operator account view — 2026-09-27

- The account page now labels each account by the phone number verified during
  Meta authorization, when available, while retaining the separate Meta phone
  ID for diagnosis. Legacy accounts without that stored number say "Número no
  disponible" rather than presenting an opaque ID as a telephone number.
- A real-database test checks tenant-scoped account retrieval through the
  admin response, and page tests cover both the verified-number and legacy
  fallback states. RED was observed before the change; focused tests are GREEN.
- Fresh checks: 529 backend tests passed with the same pre-existing reviewer
  architecture failure; 48 control-plane unit tests and TypeScript passed.
  Targeted Ruff lint/format, mypy, ESLint, Prettier and diff check passed.
  No production service, Meta setting or Zuvel number was changed. Release
  gate CLOSED; browser E2E and the isolated database-reset gate remain pending.

## Isolated connected-account browser flow — 2026-09-27

- Added a localhost-only backend fixture for Playwright. It supplies a complete
  eligible coexistence account, initial-sync status and masked HUMAN_ACTIVE
  conversation, then records a version-checked resume response. The browser
  exercises the real server-rendered account page and resume server action;
  it sees the verified number, Meta ID, sync caveat and human-control notice.
- RED was observed when the connected-account browser test had no backend;
  GREEN followed with the isolated fixture. All seven browser tests now pass.
  The existing authentication smoke expected a removed dashboard heading and
  unlabelled navigation items; its assertions were aligned with the current
  page while preserving access and logout checks. Unit tests: 48 passed;
  TypeScript and targeted ESLint passed.
- Ruling: browser tests use a local backend double, not the active backend or
  Meta, because this checkpoint must not touch live services. Cost if wrong:
  the browser pass does not prove live provider authorization, actual sync
  delivery or a deployed end-to-end flow. Those remain separate release gates.
  The local database-reset gate also remains pending. Release gate CLOSED.

## Whole-branch security review follow-up — 2026-09-28

- An independent read-only review found three high-priority gaps: outbound
  dispatch could exhaust a one-connection pool while resolving the Meta token;
  a queued or in-flight AI reply could survive a mobile takeover followed by
  administrator resume; and the partner-removal database function could mutate
  an account outside the current tenant context.
- Production outbound dispatch now resolves the account token through its
  reserved connection. A pool-size-one provider test first observed UNCERTAIN
  without an HTTP request and then ACCEPTED with exactly one request.
- Coexistence AI preparation rejects replies to an inbound that predates a
  human mobile reply, even after resume. Runtime loading and persistence also
  check this ordering so a turn in progress cannot persist a stale reply.
  Focused queued-reply and stale-turn tests observed RED/GREEN; a separate
  in-flight takeover/resume regression passed after the persistence guard.
- A new migration resolves the exact WABA/display-phone tenant for verified
  account-update webhooks, then requires tenant context for the mutating
  partner-removal function. Direct application-role cross-tenant and
  missing-context attacks observed RED/GREEN. The migration was applied only
  to the disposable security database, not to production.
- Fresh safe backend matrix: 535 passed, one known architecture failure for
  the deferred Meta reviewer-account conditionals. The database-reset gate was
  deliberately excluded because it targets the active local Supabase stack.
  Targeted Ruff lint/format, mypy and diff checks passed. This does not verify
  a live Meta provider request or the deployed end-to-end path.
- Remaining before a release decision: isolated database-reset gate, final
  operational/security review, alert notification/resolution and a supervised
  live coexistence pilot after explicit authorization. The reviewer account
  stays untouched for future Meta checks. Release gate CLOSED; no Meta setting,
  Zuvel number, production data or deployment was changed.

## Delayed inbound ordering review follow-up — 2026-09-28

- A second read-only review found that arrival order alone cannot prove a
  customer inbound preceded a human mobile reply: the webhook stores inbound
  events first and a separate worker may materialize the message only after
  the echo and administrator resume. The previous guards could then revive
  that older inbound.
- Runtime loading, persistence, and outbound preparation now also compare the
  provider event timestamps. An AI reply is superseded when any human reply
  has a later arrival sequence or an equal/later provider timestamp. Equal
  timestamps fail closed because Meta timestamps have limited precision.
- A real-database regression delayed inbound materialization until after the
  human echo and resume; it first completed an AI turn, then blocked it. A
  separate outbound regression inverted the stored arrival order to exercise
  the preparation guard; it first allowed preparation, then rejected it.
  Equal-timestamp echoes also block the stale inbound, while a genuinely new
  customer message after resume still completes an AI turn. Related focused
  tests: 19 passed. Fresh safe backend matrix: 538 passed,
  one unchanged reviewer-account architecture failure. Ruff lint and mypy
  passed; formatting was applied to the two new tests.
- The reviewer also noted a lower-priority test gap: the pool-size-one provider
  test uses a database-backed test token resolver rather than the production
  encrypted-secret resolver. That path remains for a later isolated test.
  The database-reset gate, operational alert decisions, supervised live pilot
  and production migration remain pending. Release gate CLOSED.

## Encrypted-token dispatch verification — 2026-09-28

- Closed the remaining pool-size-one test gap with the production
  `SessionFactoryMetaAccessTokenResolver`, a real encrypted secret envelope,
  and an HTTP-only Meta mock. The first run reached `UNCERTAIN` without an HTTP
  request: the vault rejected the reserved connection's session type.
- The reserved-connection resolver now reads and audits through that same
  connection. For a denied secret, it commits the denial audit before raising;
  engine-bound vault callers retain their separate committed-denial recorder.
  An invalid account/secret binding first raised the wrong error, then raised
  `SecretAccessDenied` with one persisted denial audit and no second connection.
- Both new cases passed; related outbound, disconnect, secret-isolation and
  worker-identity checks passed (22 tests). Fresh safe backend matrix: 540
  passed, one unchanged architecture failure for the deferred Meta reviewer
  account exception. Targeted Ruff and mypy passed. The database-reset gate
  remains excluded because it can reset the active local stack. No live Meta
  request, production migration, deployment or number onboarding occurred.
- Remaining release gates: isolated database-reset test, operational alert
  design/implementation decision, final security review, supervised live pilot
  with explicit authorization, and production migration/release decision.
  Release gate CLOSED.

## Isolated migration-reset check — 2026-09-28

- Created a temporary Supabase CLI project with a unique local project ID and
  database/shadow ports 55322/55320; the active local project remains on
  port 54322. The pinned CLI 2.115.0 started only the temporary database and
  applied all 25 branch migrations.
- Inserted `public.task3_review_stale_marker` into that temporary database,
  ran `supabase db reset --local --no-seed` against its explicit workdir, and
  confirmed the marker disappeared while all 25 migrations remained applied.
  The active local database container was separately confirmed healthy.
- Copied the unmodified `ensure_local_database.sh` into the temporary project
  and verified it byte-for-byte against the repository original. With the
  pinned pnpm 11.24.0 and Supabase CLI 2.115.0, it detected only the temporary
  database at 127.0.0.1:55322, reset it, and passed its own post-reset check.
  A fresh stale marker was removed, and the 25 migrations were present again.
- Ruling: do not invoke `test_database_gates.py` from the original checkout —
  it resolves that checkout's active Supabase project. The exact shell script
  and the test's observable database assertions were exercised in isolation;
  the original pytest invocation itself was deliberately not run. Cost if
  wrong: the pytest fixture/subprocess wiring remains unverified, though the
  destructive reset path and schema outcome were verified. The temporary
  project was stopped with its volume preserved. No production database or
  Meta asset was touched.
- Release gate CLOSED. Operational alert design, the final security review,
  a separately authorized live pilot and a production migration/release
  decision remain pending.
