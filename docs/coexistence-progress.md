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
