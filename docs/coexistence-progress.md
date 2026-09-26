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
