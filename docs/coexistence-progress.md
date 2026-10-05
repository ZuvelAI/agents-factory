# Coexistence implementation ledger

Approved scope: conversation plan approved 2026-09-23. Base: 4e85b3d.
Branch: codex/whatsapp-coexistence. Initial approval excluded deployment and
live-number onboarding. Subsequent explicit approval authorized the 13 production
migrations and additive six-service cutover recorded below; live-number signup
remains closed and requires its separate gates.

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
  - test_core_contains_no_customer_uuid_or_tenant_id_conditionals: baseline
    review_router.py and review-access.ts contain fixed customer UUIDs. This is
    an intentional restricted reviewer surface; changing authorization requires
    a separate decision, not a weakened scanner or removed access guard.
  - test_database_gate_removes_stale_schema_state: pnpm 11.24.0 unavailable in
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
  Missing authentication returns 401; a principal without DB membership gets 403. No token, raw payload, or secret is returned.
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

## Operations alert triage — 2026-09-28

- Added a private, forced-RLS resolution table with one insert-only record per
  ambiguous account-update alert. The note is trimmed and limited to 1–500
  characters; only the backend administrator role can read or insert. The
  migration was applied only to the disposable Supabase project on database
  port 55322, not to the active local or production database. Its schema tests
  and local database advisors passed with no new error-level finding.
- Added platform-admin alert filters, an open-count endpoint and an atomic
  manual-resolution endpoint. Concurrent closures yield one winner and one
  conflict; retries do not reopen a closed alert. Resolution is bookkeeping
  only: it does not change a WhatsApp account, agent control or dispatch.
- Replaced the Operations placeholder with open and resolved views, bounded
  pagination, a required review note, loading/unavailable states and distinct
  success/conflict/error notices. The server action validates the form and
  authenticates through the existing administrator backend path. No secret,
  webhook payload or event fingerprint is rendered in the panel.
- Fresh verification: 11 targeted database integration tests, 321 backend
  unit/contract tests, 56 frontend unit tests and 8 local-browser tests
  passed. Frontend typecheck, scoped ESLint/Prettier and git diff checks
  passed. Full frontend lint still reports two existing
  `react/no-unescaped-entities` findings at `app/review/panel.tsx:25` in the
  Meta reviewer surface that the user deferred; no new lint finding was added.
- The browser test used a local fake backend, not Meta. Final whole-branch
  review remains; a supervised live coexistence pilot, production migration
  and deployment each require a separate decision. The Meta reviewer account
  stays available and unchanged. Release gate CLOSED.

## Final Operations review and fixes — 2026-10-04

- The fresh, read-only whole-branch review identified no Critical issue and
  two Important issues: database exceptions could include an operator note
  in ASGI logs, and malformed sync-status entries could crash the account
  panel or show an empty status beside reassuring counts. Both were
  reproduced before implementation changes.
- Database parameter hiding is enabled. Alert routes handle database errors
  as a safe 503 without forwarding driver messages or exception chains, and
  validation failures no longer echo the input. NUL and unpaired Unicode
  surrogates are rejected with 422. Six new backend regressions observed
  RED then GREEN, including synthetic bound values and driver error text in
  a captured ASGI-server logging path.
- Sync-status responses now validate each entry, unique supported types,
  state, timestamp and state-specific request metadata before rendering.
  Six malformed-response regressions observed RED then GREEN. The form also
  rejects NUL before calling the backend.
- The reviewer marked whitespace-only database notes and missing sensitive-
  note guidance Minor. These were regraded as required-spec fixes: audit
  notes are immutable and their validation and operator guidance are explicit
  requirements. A new CLI-generated migration aligns the trim check with
  Python whitespace, including tabs, newlines and Unicode spaces; the schema
  regression observed RED then GREEN. The note field now explains not to
  include tokens, credentials or message contents, with accessible help text.
- Fresh safe backend suite: 522 passed, one explicitly deferred reviewer-
  account architecture test deselected. This run excluded the active-stack
  reset test, unavailable Redis lock test, and the two canonical-port tenant/
  secret suites; their prior isolated evidence is retained above, not claimed
  as rerun. Frontend: 62 unit tests and 8 local-browser tests passed. Scoped
  ESLint, frontend typecheck, targeted Ruff/mypy and diff checks passed.
  Full frontend lint retains the two deferred reviewer-page findings.
- Applied the follow-up migration only to the known disposable project at
  port 55322, then rebuilt all 27 migrations there and reran the 11 alert API/
  schema integration tests successfully. Database advisors found no error-
  level issue. The active local database remained healthy; the original
  checkout stayed clean at checkpoint `4e85b3d`.
- Final Ruling: live Meta behavior and rollout readiness remain outside this
  local review, as authorized by the user. Cost if wrong: local tests do not
  establish actual eligibility, signup, provider delivery or synchronization
  for Zuvel's number; the supervised pilot and release gate remain required.
- Final Ruling: retain the Meta reviewer account and its known architecture/
  lint exceptions for the user's deferred correction. Cost if wrong: the
  complete repository gate is not green; no full-release approval is claimed.
- All findings from this review were addressed with reproduction-backed
  verification; no Minor finding from this review remains deferred. No live
  Meta request, production migration, deployment or number onboarding occurred.
  Release gate CLOSED; reviewer correction, supervised pilot and production
  migration/release decision remain pending.

## Deferred reviewer correction — 2026-10-04

- User continued after the final Operations stage; implement the previously
  deferred internal correction, not a customer demo. Existing credentials,
  Supabase user metadata/expiry, Meta assets and deployed services are untouched.
- Removed the customer-specific UUIDs from application code without weakening
  the architecture scanner. Backend and panel use the same five server-only
  `META_REVIEW_*` identifiers. The existing binding is retained explicitly in
  `infrastructure/meta-review-binding.env.example`, outside the reusable core.
  Blank/partial configuration denies reviewer access; invalid backend values
  produce sanitized configuration errors. No permissive built-in fallback.
- Backend still fetches the current Auth user, checks non-anonymous reviewer
  role, exact tenant/account and timezone-aware expiry, and revalidates active
  WABA/phone identity. Added an API_ONLY restriction so reconnecting the record
  as COEXISTENCE cannot repurpose the reviewer surface for the live pilot.
  One configured recipient, the daily cap and platform-admin denial remain.
- Backend auth configuration and API_ONLY regressions observed RED then GREEN.
  The panel guard's missing-config/alternate-binding/anonymous-account cases
  observed RED then GREEN. Actions verify the current user before forwarding
  a session; the displayed recipient is masked and only server configuration
  chooses the actual destination. Fixed the two escaped-apostrophe lint errors.
- Fresh verification: 541 safe backend tests, 74 frontend unit tests, full
  frontend ESLint, TypeScript, targeted backend Ruff/mypy and diff checks pass.
  The architecture test now passes without deselection. The safe backend run
  still excludes the original-stack reset test, unavailable Redis lock test,
  and the two canonical-port security suites; those are not waived or claimed
  freshly verified. All 8 local-browser tests also passed with fake Auth/backend
  servers; no real Meta or reviewer credentials were used.
- Ruling: deploy this correction only together with the unchanged five-value
  reviewer profile on both servers — avoids a customer-specific default in
  reusable code while retaining the approved review scope. Cost if omitted
  or mismatched: reviewer access fails closed; deployment remains gated until
  the authorized operator verifies configuration parity and reviewer login.
- Release gate CLOSED. No push, merge, deployment, production migration, live
  provider request, credential change or Zuvel number onboarding occurred.
- Final review: independent read-only review of `9412798..a3d7974` found no
  Critical or Important regression. It confirmed the exact backend scope,
  recipient, API_ONLY and current-metadata checks and server/client boundary.
- Final: minor (deferred): narrow the prior ruling's configuration-mismatch
  claim. Missing/partial configuration denies access, but a control-plane-only
  WABA/phone mismatch can still allow login and submissions. Five-value parity
  requires the documented operator check; successful login is not proof of
  parity. This qualifier supersedes the blanket mismatch claim above; the
  deployment checklist already explicitly requires the parity check.
- Final Ruling: the reviewer set aside live Auth account, scope/expiry and
  deployed configuration — keep remote mutation/readiness outside this local
  correction. Cost if wrong: live availability remains unproved; authorized
  configuration parity and reviewer smoke checks are required before rollout.
- Final Ruling: the reviewer set aside live Meta templates, delivery and asset
  acceptance — no provider call or worker was authorized. Cost if wrong: mocks
  cannot establish actual provider behavior or eligibility for Zuvel's number.
- Final Ruling: the reviewer set aside the supervised pilot and production
  rollout — preserve their separate authorization gates. Cost if wrong: the
  implementation does not yet establish safe live coexistence operation.
- Final Ruling: the reviewer set aside excluded reset, Redis and canonical-
  port suites — do not weaken their safety guards or touch the active stack.
  Cost if wrong: those complete-environment regressions remain unverified in
  this run; prior evidence is retained, not a fresh full-suite claim.
- Final Ruling: the reviewer set aside browser smoke results — the author
  separately ran and read all 8 passing local-browser cases. Cost if wrong:
  mocked local smoke is not an independent review of the live deployed path.
- Final Ruling: the reviewer set aside full-repository/production readiness —
  this is a scoped correction, not release approval. Cost if wrong: additional
  environment/pilot/deployment checks may still uncover release blockers.

## Environment regression gates and rollout preparation — 2026-10-04

- Continued after `ce58f3f`, without repeating the reviewer implementation or
  its review. All test data/services remain local and disposable; no remote
  database, Meta setting, account metadata or real number changed.
- Built a temporary source snapshot at
  `/private/tmp/aiworkers-coex-gates-8LSNB9` from the saved branch, with only its
  Supabase configuration pointing to the existing disposable project on
  55322/55320. The reset script and database/security test files were copied
  byte-for-byte. A dedicated Redis container used loopback port 56379 and tmpfs
  storage, not the active application's Redis.
- Ruling: use actual cached pnpm 11.24.0 and Supabase CLI 2.115.0 with the
  already-installed locked dependencies; disable pnpm's automatic reinstall
  only in the temporary snapshot — avoids rewriting the worktree's symlinked
  dependency directory. Version, no-linked-project and loopback/canonical-port
  guards remain unchanged. Cost if wrong: this does not prove a fresh dependency
  installation or the complete CI aggregate command; those are not claimed.
- Initial all-in-one pytest run: 574 passed, one failed because the unit
  runner double returns port 54322 while the disposable project's configured
  port is 55322. The actual reset, Redis, tenant and secret integration suites
  passed in that run.
- Ruling: run unit/contract tests in the unchanged isolated worktree and
  integration/security/architecture tests in its temporary snapshot — preserves
  the canonical-port rejection instead of relaxing it or resetting the active
  54322 project. Cost if wrong: the proof is a partitioned complete pytest
  collection, not a single all-in-one run; no test is permanently deselected.
- Fresh final backend evidence: 344 unit/contract tests and 237 integration/
  security/architecture tests passed (581 total, including the six new deployment
  cases). The previously excluded original-stack reset, Redis conversation lock,
  canonical tenant matrix and encrypted-secret isolation suites are now exercised
  safely. The reset removes the stale marker and reconstructs all 27 migrations.
- Deployment validation found both Compose manifests omitted the panel's new
  reviewer binding; local backend wiring was also missing, and VPS host overrides
  could diverge from its backend env_file. Four populated/override regressions
  failed before the fix. A shared server-only environment mapping now passes
  the same five interpolated identifiers to both servers without giving the panel
  the backend's master key, Meta secret or OpenAI key. All six populated,
  overridden and absent-binding cases pass after the fix and YAML formatting.
- SQL release matrix initially failed tests 190 and 192: six public tenant-owned
  tables were absent from its registry. Added onboarding configs, contacts,
  history inbox/messages/import receipts and sync requests, keeping every
  existing policy/catalog assertion. RED: 191/193; GREEN: 247/247 pgTAP assertions
  passed on the disposable project. No migration or database privilege was
  changed to make the gate pass.
- All 74 panel unit tests pass fresh. New Python test Ruff/format, modified
  YAML/Markdown Prettier and diff checks pass. SQL lint found no error-level
  issue in public or agents_factory_private on the disposable project.
- Public read-only observation: `https://aiworkers.zuvel.ai/health/ready`
  returned `{"status":"ready"}`. Ruling: treat this only as panel liveness —
  the route is static and cannot prove backend/database readiness, deployed
  reviewer configuration, version or Meta eligibility. Cost if wrong: a live
  deployment could still be incompatible or unavailable; remote preflight and
  reviewer checks remain required.
- Added `docs/coexistence-rollout-checklist.md`: exact-environment approval,
  separate data/queues, backup/restore proof, migration comparison, restricted
  reviewer preservation, webhook/worker ownership, a future Zuvel-only activation
  gate, owner-operated Meta pilot and compatible-version rollback. It explicitly
  forbids global gate removal, API_ONLY fallback, number deregistration, blind
  one-shot retries, remote resets and automatic schema rollback.
- Release gate CLOSED. No staging/production deployment, push, merge, live
  provider request, worker activation or number onboarding was performed. A
  separate staging environment has not been confirmed, and no remote SSH target
  was guessed from the VPS hostname.
- Independent final review of `ce58f3f..c0760f8`: no Critical, Important or
  actionable Minor finding. The reviewer independently reran all six real
  Compose configuration cases and diff checks, and read the broader saved
  backend/SQL logs; it did not independently rerun those broader suites.
- Final Ruling: the reviewer set aside the older reviewer-account implementation
  beyond configuration compatibility — retain its already completed scoped
  review, do not pay for another review of unchanged code. Cost if wrong: the
  present review cannot substitute for the earlier auth/recipient test evidence.
- Final Ruling: the reviewer set aside live reviewer availability, credentials,
  role and expiry — preserve them and require authorized remote smoke/parity
  checks before rollout. Cost if wrong: a correctly wired candidate can still
  leave the deployed reviewer unavailable.
- Final Ruling: the reviewer set aside production readiness, fresh installation
  and aggregate CI — this stage proves regression/configuration behavior, not
  complete release readiness. Cost if wrong: clean-build or deployment gates
  may still expose a blocker; no release authorization is inferred.
- Final Ruling: the reviewer set aside live Meta acceptance, eligibility,
  delivery, sync and mobile takeover — keep those in the supervised pilot.
  Cost if wrong: local evidence cannot establish behavior for the real number.
- Final Ruling: the reviewer set aside remote migration compatibility, real
  backup recovery and isolated staging existence — identify the actual target
  and verify these before external changes. Cost if wrong: shared queues/data
  or an incompatible recovery version could harm the current deployment.
- Final Ruling: the reviewer set aside future tenant-scoped activation code —
  it is not implemented or authorized by this scoped preparation change; both
  current signup gates stay closed. Cost if wrong: the real pilot cannot yet
  be started; never remove the gate globally as a workaround.
- Cleanup: stopped and removed only `aiworkers-coex-gates-redis-8lsnb9`, the
  tmpfs-backed Redis created for this run; no durable application data existed
  there. Test logs remain in the temporary snapshot. The active Supabase project
  remained healthy with its pre-run start time, and the original checkout
  remained clean at `4e85b3d`. The disposable database also remains healthy.

## Zuvel production pilot authorization and read-only preflight — 2026-10-04

- The owner explicitly chose a supervised pilot on the existing production
  installation rather than a separate staging environment. Scope is Zuvel and
  its previously authorized Business-app number, not general coexistence
  availability. The owner continues to perform Meta UI/phone actions manually.
- Recovered the existing SSH destination from a narrowly scoped connection
  history match and used the dedicated local Zuvel deployment key with strict
  known-host verification. No key, password or token was printed or changed.
- Confirmed `/opt/aiworkers` and the running AI Workers Compose project. Backend
  readiness reports database and Redis up; dashboard liveness also responds.
  Backend/panel and the three inspected workers have different running image
  generations. Their image identities were read, not overwritten or restarted.
- Read-only admin-role database preflight confirms one visible tenant, Zuvel
  (`c5cd8d04-01f2-49be-aa27-1075520a2a20`), and its existing API_ONLY account
  (`d4dfa61a-7ed6-4a87-877a-1d34e7dbf837`). Eligibility is UNKNOWN. The durable
  outbox contains three succeeded jobs and no pending row in this observation.
  This does not prove queues are empty or the real number is accepted by Meta.
- Initial reads without the admin role returned no tenant/account rows because
  of RLS. Repeated the inventory using the existing application's admin role
  within an explicit READ ONLY transaction; did not change roles, policies or
  grants. Reading Supabase migration history fails with SQLSTATE 42501 under
  the runtime connection. No permission change or migration was attempted.
- Production lacks the new five-value reviewer environment profile; its current
  older image still has the earlier binding. Preserve that identity when the
  candidate is deployed rather than replacing or converting its account.
- Ruling: the production choice supersedes the staging requirement, not backup,
  compatibility, single-scheduler or tenant/number guards — those remain needed
  even with one client. Cost if wrong: an unsafe update could disrupt Zuvel's
  messages or reviewer access; read-only preflight is not deployment approval
  evidence or proof of recoverability.
- Proposed bounded follow-up: a server-owned, default-closed, single-tenant
  signup permission and exact provider-verified phone restriction, consumed by
  the existing panel flow. Start and completion recheck the permission; missing
  or malformed configuration never opens general onboarding. Closing signup is
  not an outbound kill switch; use existing mobile takeover and explicitly stop
  the named AI Workers outbound/agent execution if a pilot must be halted.
- All actions in this preflight were read-only. No deployment, remote file
  change, migration, worker activation, live Meta request or onboarding occurred.
  Existing signup gates remain CLOSED. The 28 local signup unit/contract tests
  passed fresh; no broader regression rerun is claimed for this preflight.

## Zuvel-only pilot permission and additive production recovery — 2026-10-04

- Continued from `0b793bc` in the existing isolated branch. The owner reiterated
  that nothing on the shared VPS may be deleted. No file/container/image/volume
  deletion, service restart, deployment, migration or live Meta action occurred.
- Implemented a server-owned pilot permission requiring both
  `COEXISTENCE_PILOT_TENANT_ID` and `COEXISTENCE_PILOT_PHONE_DIGITS`. Missing,
  blank or partial configuration leaves coexistence signup closed. Invalid
  identifiers fail sanitized configuration validation. Start and callback both
  recheck the exact tenant; the provider-verified number is checked before any
  account or credential write. API_ONLY and the reviewer binding are unchanged.
- The authenticated admin availability endpoint returns only a boolean. The
  panel fetches it server-side without caching; missing, failed or malformed
  responses remain closed. An availability failure does not hide existing
  accounts. An enabled pilot still requires an explicit mode choice and current
  Meta eligibility/ownership evidence, not a forced ELIGIBLE status.
- Both Compose manifests pass the optional pilot settings only to the Python
  runtime, not the panel browser/server. The existing five-value reviewer
  binding remains identical on backend and panel, including host overrides.
- TDD evidence: backend 14 failed/71 passed before the implementation, panel
  8 failed/74 passed, Compose 3 failed/3 passed and pilot browser 1 failed/2
  passed. Final fresh backend partition: 362 unit/contract plus 237 integration/
  security/architecture tests passed (599 total). Panel: 82 unit tests and all
  9 local browser tests passed. Compose: all six actual configuration cases
  passed. The browser uses fake Auth/provider fixtures, never the real number.
- Initial aggregate validation had nine failures: unavailable Node/Docker in
  its narrowed PATH, a missing disposable encryption key, and the already-known
  canonical-port fixture mismatch. A subsequent integration run retained a
  stale marker from the interrupted reset. Restored the normal executable PATH,
  supplied a test-only key and reconstructed only the disposable 55322 project;
  the fresh 237-test run then passed. The unchanged canonical-port unit gate ran
  in the worktree. No guard was weakened or test permanently deselected.
- Ruling: retain partitioned regression proof using the unchanged worktree
  and temporary snapshot, not an all-in-one green claim. Cost if wrong: this
  does not establish a fresh dependency installation or aggregate CI run.
- Added private recovery artifacts under
  `/opt/aiworkers/.recovery-coex-20261004-l7fySG` (directory 700, files 600).
  The deployment/configuration archive, available backend/panel/Redis images,
  old worker filesystems and seven private container configurations pass archive
  and checksum checks. The first image-save attempt failed because the running
  worker images are no longer present in Docker's image store; its partial
  archive is retained, not overwritten or deleted. Worker exports did not pause
  the running services. Shared worker generations are recorded separately from
  the outbound worker generation.
- Ruling: intact image/filesystem/configuration archives are recovery material,
  not a completed restore drill. Cost if wrong: restoring commands, dependencies,
  data/queues and schema compatibility remain release gates before cutover.
- Read-only Supabase management access confirms the exact production project,
  14 remote migrations and 13 pending candidate migrations. The first 11 remote
  statements exactly match local checksums; the remaining three baseline changes
  match semantically despite comments/whitespace and different history versions.
  All 13 pending SQL files were read. Do not blindly push 27 local versions or
  rewrite the legacy remote history. No remote DDL/DML was executed.
- Production inventory: 24 application tables, two Auth users and no Storage
  buckets/objects. A protected database backup and separate restoration proof,
  reviewer smoke/configuration parity, candidate clean build and scheduler/queue
  ownership checks still gate production changes. Zuvel's real number has not
  been onboarded or shown eligible. No push or merge was performed.
- The local optimized Next.js build also completed with fictitious loopback
  Auth/backend settings, without real provider calls. ESLint, TypeScript, Ruff
  and diff checks passed. The build-generated next-env path change was restored;
  no generated output belongs in the source commit. This is not a clean Docker
  dependency installation or a deployed-image claim.
- The owner authorized Supabase CLI's macOS Keychain request directly. The CLI
  initialized its normal login role and saved a protected application schema
  dump. Production application schema/data remain unchanged; completing the
  data/Auth/history backup and proving a disposable restoration remain pending.

## Restored production rehearsal and bounded panel fetch — 2026-10-04

- Resumed the unfinished recovery gate; no production migration, application
  deployment, restart, queue flush, number onboarding, push or merge occurred.
  The seven production containers retain their original running start times.
  Added backup files only to the existing private recovery directory. A command
  approval timeout/usage-limit interruption delayed local verification; after
  permission review became available, resumed the same checks without bypassing it.
- Saved application and managed Auth/history schemas, application/Auth/history
  data and custom role definitions in the protected local recovery directory
  `/private/tmp/aiworkers-production-recovery-gPonVmPZ` and copied the five SQL
  artifacts to the private VPS recovery directory. Checksums pass. Existing
  runtime passwords, encryption key and reviewer credentials were not changed.
- Restored into a new local database, `aiworkers_coex_restore_20261004`, on the
  disposable 55322 project, never into its working test database or production.
  The first non-superuser owner-restore attempt rolled back transactionally;
  the existing local Supabase bootstrap owner restored the unmodified dumps.
  The CLI data filter omitted 82 Auth migration versions: recovered their exact
  version-only rows separately. All 52 source tables then matched row counts
  and canonical row-content fingerprints. No plaintext data was printed.
- Applied all 13 pending migrations transactionally only to that restored copy.
  Existing tenant/account/Auth, audit and encrypted rows remained: tenant 1,
  WhatsApp account 1, Auth users 2, audit events 40, encrypted records 3; legacy
  migration history remains 14 and the two old signup states remain API_ONLY.
  This rehearsal intentionally does not add production migration history rows.
- Ruling: retain the verified remote legacy migration identifiers rather than
  repairing or pushing all local versions — the first 11 baseline SQL changes
  match exactly and the remaining three match semantically. Cost if wrong:
  pending-only deployment still needs correct history recording and lock checks;
  the local rehearsal is not proof of production application.
- Backed up the AI Workers Redis RDB without stopping or flushing Redis. The
  first checksum utility invocation could not seek stdin; verified the same
  retained snapshot through a new temporary file instead. Checksum and RDB
  checks pass, with 69 keys observed. This does not prove the live queues are
  empty; no queue contents or message values were exposed.
- The restored-copy pgTAP run initially failed 12/360 assertions. Investigation
  found two stale harness assumptions (two rather than four approved private
  SECURITY DEFINER functions; exactly two total tenants), plus ten failed
  default-privilege checks. The schema-filtered dump omitted PostgreSQL's global
  function defaults; a read-only production query confirmed the original
  `postgres` global function ACL is owner-only. Added a protected separate SQL
  backup of that setting and restored it only locally. The probes explicitly use
  the migration owner, not the managed CLI login role. No production ACL changed.
- Ruling: adapt foundation fixtures to existing data and the two previously
  implemented coexistence webhook functions, while preserving the exact definer
  allowlist and adding app-only grant/empty-search-path assertions — this tests
  the current schema without deleting restored rows or weakening public access
  guards. Cost if wrong: an incorrectly approved privileged function could bypass
  tenant isolation; signature-specific grants and existing disconnect/security
  integration coverage remain mandatory.
- Before restoring the missing global ACL, the corrected tests still failed
  all ten execution-denial checks (115 foundation plus 247 isolation assertions).
  After restoration: `supabase test db --db-url` on the explicit loopback restored
  database passed both files, 362/362 assertions. Standard local `extensions`
  schema bootstrap was needed because this disposable restore started empty.
  No application policies or public grants were relaxed.
- Recovery of the original application key is proved: the saved private backend
  configuration decrypts all three restored envelopes in a READ ONLY local
  transaction after migrations. Values are used only in memory and never printed,
  persisted or sent to Meta. The local probe initially used an unavailable
  driver; switched to the already-installed runtime asyncpg driver, without
  installing a package or changing dependencies.
- Fresh independent review of `0b793bc..de9d95c`: no Critical or Minor findings;
  one Important finding, optional pilot availability could block existing account
  controls indefinitely. Kept that grade because it affects already-connected
  users, not just the new pilot. No re-review was dispatched.
- Final: fixed unbounded optional availability — real browser regression
  `stalled optional availability preserves existing account controls and keeps
  signup closed` timed out before the change, then passed after the server-only
  helper bounds Auth plus fetch with a two-second deadline and aborts the request.
  Fresh full panel suite: 82/82 unit and 10/10 browser tests; typecheck and ESLint
  pass. Final optimized Next.js build passes using fictitious loopback values.
  Fresh unchanged backend unit/contract partition: 362 passed. Earlier 237-test
  integration/security/architecture proof remains recorded, not rerun against the
  restored copy because those fixtures truncate data. No aggregate CI claim.
- Ruling: a timeout closes only optional coexistence signup and preserves existing
  controls — no cached positive permission or API_ONLY fallback. Cost if wrong:
  a slow healthy provider/backend may temporarily hide an authorized pilot until
  refresh; it cannot open onboarding without current server permission.
- Final Ruling: the reviewer declined live Meta eligibility, Embedded Signup
  configuration and mobile preservation — retain a supervised owner-run live
  gate; approval/publishing is not number acceptance. Cost if wrong: onboarding
  could fail or phone-app access could change; do not force eligibility.
- Final Ruling: the reviewer declined deployed runtime parity and reviewer login —
  preserve the five-value identity on both servers and verify scoped access at
  deployment. Cost if wrong: the reviewer could lose access or receive admin
  controls; local fixtures do not prove the live Auth account is valid.
- Final Ruling: the reviewer declined recovery, pending migrations and old/new
  image compatibility — database/data/key restoration and pending SQL are now
  rehearsed, but container recovery and deployed-image compatibility remain open.
  Cost if wrong: archive integrity alone cannot guarantee a working rollback.
- Final Ruling: the reviewer declined scheduler/queue ownership, webhook delivery
  and real outbound takeover — keep these as release/pilot gates and never run
  duplicate schedulers on the shared outbox. Cost if wrong: duplicate or unexpected
  messages could be sent; an RDB copy is not proof of idle queues.
- Final Ruling: the reviewer declined in-flight revocation guarantees — startup-
  loaded signup permission is not an instantaneous outbound kill switch or recall
  of a dispatched request. Cost if wrong: an in-flight reply may still arrive;
  explicit mobile takeover and scoped execution pause remain the pilot response.
- Final Ruling: the reviewer declined prior broad implementation and full suite
  replication — its 93 targeted passing checks and this fix's full frontend suite
  supplement, not replace, the recorded backend partitions. Cost if wrong:
  clean dependency builds, actual deployment and external behavior can still fail.
- Deferred minors: none from this fresh review. Remaining gates: candidate clean
  Docker build, container recovery/old-new schema compatibility, live reviewer
  scope/configuration, single-owner queues/scheduler, current Meta flow evidence,
  then supervised real-number pilot. All VPS material remains retained.

## Packaged runtime compatibility and recovery proof — 2026-10-04

- Clean locked Linux/amd64 Docker builds from `e437e8c` pass; VPS architecture
  is x86_64. Runtime image `aiworkers-coex-runtime:e437e8c` is
  `sha256:d82b6a0d6244c8fb878ae19812ea653b63896a7f49481e12b87cf33737ba23f0`;
  dashboard `aiworkers-coex-dashboard:e437e8c` is
  `sha256:76ea9f364077185996f61725b1751d7b0e629201d2afdf82decae6a3ca15033d`.
  Both carry the complete source revision label. The dashboard uses only the
  saved production public Supabase URL/publishable key as build configuration;
  no private backend environment, provider secret or master key enters it.
- Packaged dashboard smoke, isolated without networking: liveness and login
  return 200; unauthenticated private tenant access redirects to login. The
  runtime imports API and all four worker modules without starting consumers.
- Downloaded verified production backend/panel/Redis image archive and imported
  it locally by its saved IDs (no repository tags or local aliases overwritten).
  Copied the two worker filesystem backups and Redis RDB; all SHA256 values
  match the VPS copies. Reconstructed the old agent and outbound images locally
  using their saved app user, working directory and only PATH/PYTHONPATH/virtual
  environment settings. Both modules import with no network and no worker start.
- Recovered Redis RDB loads successfully in a new isolated local container:
  checksum valid, 69 records in the original snapshot, four unexpired keys at
  load time. Snapshot mount is read-only; no AOF/save, public port or worker.
  The test instance exits with `shutdown nosave`; live Redis was not touched.
- Previous production backend and candidate both pass real DB/Redis readiness
  and read the existing API_ONLY review account from the restored, migrated DB.
  Queries are READ ONLY under session identity `agents_factory_app`, exercising
  its existing SET-role permission to `agents_factory_admin`; account ID, WABA
  and phone ID remain exact. The first probe wrongly assumed the local postgres
  login could SET the admin role; it correctly failed because its membership
  has SET FALSE. Corrected only the test session identity, not grants or source.
- Ruling: this is pre-onboarding API_ONLY compatibility, not proof that old
  images understand future coexistence records — retain a new compatible image
  for post-onboarding incident recovery. Cost if wrong: promoting the older API
  after onboarding could mishandle a real account despite passing this smoke.
- Live reviewer Auth metadata checked read-only: one scoped reviewer, matching
  tenant/account, confirmed, not banned/deleted, expiry remains
  `2027-10-01T00:00:00+00:00`. Credentials and metadata were not changed. This
  is not a password-login or deployed reviewer-permission smoke.
- No local host arq/uvicorn consumers found; only two local database containers
  and the dedicated pilot Redis are running. VPS still has the same seven
  AI Workers services and original start times. Durable outbox contains only
  three succeeded jobs; agent/knowledge/outbound Redis queues read zero.
  Scheduler snapshots contain one or two recurring jobs and about 60 guards
  with up-to-one-minute TTL, rather than an assumption that all keys are idle.
- Ruling: inspect and preserve scheduler guards rather than clearing them —
  arq retains completed cron guards briefly for deduplication. Cost if wrong:
  read-only snapshots still cannot guarantee no new work at cutover; pause the
  named scheduler, recheck real jobs and allow graceful consumer drain first.
- Ruling: do not use standard Compose recreation for this deployment — the
  owner's preserve-everything constraint requires an additive release and new
  containers, retaining the old containers/configuration/images. Cost if wrong:
  cutover takes a bounded service interruption and explicit network/port handling;
  no unrelated VPS service or Redis volume may be removed or replaced.
- Fresh reviewer decisions remain unchanged: live Meta eligibility/mobile flow,
  deployed reviewer login, actual deployment/recovery behavior, queue ownership
  and real webhook/outbound takeover remain explicit gates. No deferred minors.
  No remote migration, application replacement, worker start, live Meta call,
  number onboarding, real send, merge or push occurred in this recovery stage.
- Prepared an additive private candidate directory on the VPS:
  `/opt/aiworkers/.candidate-coex-e437e8c-pJU10x`, mode 700. Both source and
  image archives match their local SHA256 values; the two new image tags were
  absent before import. Image IDs, Linux/amd64 architecture and full revision
  labels match the clean local builds. No existing tag was overwritten.
- Validated the separate six-service manifest without creating containers.
  It reuses only the existing external AI Workers network and Redis endpoint,
  retains the loopback ports, uses distinct container names and has no Redis
  service/volume definition. A new private `original.env` copy matches the
  current deployment byte-for-byte. The copy utility's no-clobber portability
  warning is benign: target absence was asserted first and equality afterward.
- In-memory configuration comparison passes: original database URL, master key,
  provider secrets and Supabase Auth settings unchanged; five exact reviewer
  values identical on API and panel; panel has only those five and its three
  required connection/public settings. Both pilot permission values stay blank
  on all runtime services, so onboarding remains closed. No secret was printed.
- Ruling: use a deployment-only migration bundle with the exact 14 existing
  identifiers/statements plus the 13 unchanged pending source files — preserve
  historical records instead of repairing or blindly including old versions.
  Cost if wrong: future deployments must repeat this history-aware preparation;
  standard pushes from the canonical checkout still encounter legacy IDs.
- Current production query confirms all 14 exported historical SQL hashes
  match exactly. Supabase CLI 2.115.0 `db push --dry-run --skip-vault` against
  the named production project succeeds and lists exactly the 13 pending
  migrations, no seeds or application roles. The CLI initializes its managed
  login role, but applies no application migration or Vault update. No CLI
  upgrade, history repair or include-all was used. The generated temporary
  bundle is `/private/tmp/aiworkers-coex-release-migrations-vWqUgKa5`.
- Saved its private archive beside the candidate, SHA256
  `1ce98d8789a037a7179e4d978ab8b159258512260553976e6a11e1972fbaeef1`.
  The source archive is
  `43abe3a638fb3c92beff88cc496b126e89570a693a15abe0e40385bb5b88f19c`;
  image archive is
  `09ed4434390ed1f0f5af687b36cf219d36ce1727d0a1245bdcf5fd0f0891cb9a`.
- Final read-only check still finds all seven original VPS containers with
  their original start times. About 60 in-progress keys all identify the known
  dispatch cron; its installed arq implementation retains these for 60 seconds.
  One/two queued scheduler entries also identify this recurring dispatch.
  Snapshots are intentionally not claimed atomic; no customer work was queued
  in agent, knowledge or outbound. Do not manufacture idleness by flushing.
- Next boundary: actual production schema application and six-service cutover
  require explicit confirmation of this concrete security-sensitive change and
  short AI Workers interruption under executing-plans. Retain all old containers,
  files, images and Redis; never use recreation/removal as the cutover shortcut.
  After cutover, verify live reviewer access before opening the Zuvel-only signup
  gate; the owner still performs Meta/phone actions, with no computer use.

## Approved production cutover — 2026-10-04 / verified 2026-10-05

- Owner explicitly approved applying the 13 pending migrations and replacing
  only the six AI Workers application services, preserving every old container,
  Redis and unrelated projects. This supersedes the preceding approval boundary,
  not the separate reviewer-login and real-number onboarding gates.
- Supabase CLI 2.115.0 applied the exact 13 pending source migrations using the
  history-aware deployment bundle and `--skip-vault`; exit 0. Subsequent dry run
  returned no pending migrations, seeds or roles. Production history now contains
  27 entries. No history repair, reset, Vault/config/Auth push or engine upgrade.
- Fresh read-only checks on 2026-10-05: one tenant, one WhatsApp account, two Auth
  users; zero public tables without RLS and zero tables directly accessible to
  anon/authenticated. All four internal security-definer functions are in
  `agents_factory_private`, have empty search_path, allow the application role
  and deny both browser roles. A preliminary query for schema `private` returned
  no rows; the exact function-name check above establishes the actual schema.
- The security advisor reports only the pre-existing disabled leaked-password
  protection warning, unchanged before/after migration. It is not an introduced
  schema issue; no global Auth setting was changed under this deployment scope.
- Gracefully stopped the original scheduler first, then its three consumers;
  queues agent/knowledge/outbound read zero and durable outbox contains only
  three succeeded jobs. Preserved completed cron guards without flushing Redis.
- Retained all six original containers with their original IDs, stopped. The
  replacement API and panel use the verified e437e8c image IDs, same loopback
  ports and existing network. Measured web cutover was 28.75 seconds; backend
  readiness and panel liveness passed before worker activation. No Nginx change.
- On 2026-10-05, started the three replacement consumers, then exactly one
  replacement scheduler. All four heartbeat values changed from their prior
  values within the bounded startup check. Final verification finds all six
  new containers running with zero restarts; API/panel Docker health is healthy
  and all four heartbeat keys have positive TTLs. Original containers remain
  present/stopped; Redis and the other previously running container keep their
  original IDs, images and start times. Redis volume is unchanged.
- Twelve read-only HTTP checks pass: API readiness and panel liveness 200,
  unauthenticated admin signup availability 401, loopback/public login and
  reviewer-login 200, protected reviewer/tenant routes 307 to /login, and public
  webhook GET without required parameters 422. This proves routing/validation,
  not actual provider webhook delivery, authenticated access or message sending.
- Probe diagnosis: the initial expected /review/login redirect was incorrect;
  the existing proxy sends unauthenticated /review to /login. Source and live
  headers agree. Public Python-urllib requests received 403 while curl and an
  explicitly identified verification client received 200. Only the temporary
  probe expectation/User-Agent changed; application/access rules were untouched.
- Fresh configuration comparison verifies original database URL, master key,
  provider secrets and Supabase Auth settings unchanged. All six containers
  preserve the five exact reviewer bindings. Both pilot settings remain blank
  on every runtime service, so coexistence signup remains closed.
- The dedicated reviewer identity is still confirmed, not banned/deleted,
  exactly scoped to its original test tenant/account, expires 2027-10-01 UTC.
  This is metadata/configuration evidence, not a password-login smoke. No
  credential or expiry change, account conversion, provider call or test send.
- Final queues remain zero and durable outbox remains three succeeded jobs.
  These snapshots do not establish future idleness or instantaneous cancellation
  of a provider request already in flight. Existing approved service duties may
  resume; no synthetic message/job was inserted to prove deployment.
- Private candidate/backups remain available at their previously recorded
  locations. Local read-only verification helpers were added under the protected
  recovery directory; nothing on the VPS was deleted, pruned or overwritten.
  No merge or push. Application build revision remains e437e8c; this entry is
  deployment evidence, not a new application image.
- Next gate: owner manually signs in at /review/login with existing Meta-review
  credentials and confirms the original restricted API_ONLY review screen and
  lack of administrative/customer controls. Do not refresh templates or send a
  message as part of that check. Only after this gate and separate activation
  approval should the exact Zuvel tenant/number signup permission be configured.
  The owner then performs Meta/phone onboarding; real coexistence acceptance,
  mobile echo, AI takeover, inbound/outbound delivery and disconnect behavior
  remain unverified live gates. This deployment does not complete the pilot.
