# WhatsApp Account-Update Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show ambiguous WhatsApp account-update alerts in AI Workers Operations and let a platform administrator resolve one with an auditable note, without changing any WhatsApp account or agent state.

**Architecture:** Preserve the immutable webhook alert table. Add an insert-only private resolution table, extend the authenticated backend with filtered reads, an open count and an atomic resolve endpoint, then replace the Operations placeholder with server-rendered lists and a confirmed server action. Duplicate events and concurrent resolutions remain safe.

**Tech Stack:** PostgreSQL/Supabase migrations and forced RLS; Python/FastAPI/SQLAlchemy/Pydantic; Next.js 16.3.2/React 19; pytest, Vitest and Playwright.

**Spec:** `docs/superpowers/specs/2026-09-28-whatsapp-account-update-alert-operations-design.md`

**Status:** All three tasks implemented locally. Independent review completed;
findings fixed and verified on 2026-10-04. Evidence and remaining gates are in
`docs/coexistence-progress.md`. Release gate CLOSED; integration and live pilot
remain separate decisions.

## Global Constraints

- Work only in the existing isolated `codex/whatsapp-coexistence` worktree; do not change the original checkout, Meta configuration, live number, remote database, or production deployment.
- Keep the coexistence release gate closed. Preserve the Meta reviewer account; the customer-demo account remains deferred.
- Run database tests only against a verified disposable local project with a unique project ID and non-default database port. Never run `make test-integration`, the original checkout's database-reset gate, or `supabase db reset` against the active stack.
- Do not run `infrastructure/scripts/check_repository_security.sh` against the original local Supabase project: it invokes database tests and advisors implicitly. Run its relevant checks only with the isolated project or report them as pending.
- Before schema implementation, check the [Supabase breaking-change changelog](https://supabase.com/changelog?types=breaking-change), [RLS guide](https://supabase.com/docs/guides/database/postgres/row-level-security), and the pinned CLI's `--help`. Create the migration with `supabase migration new`, then edit the generated file with `apply_patch`.
- The resolution note is trimmed, nonempty and at most 500 characters. Do not log it or expose tokens, webhook payloads, or event fingerprints through the API or panel.
- Reuse the platform-admin JWT and current membership check; never place a service-role key in browser code. Read the relevant `apps/control-plane/node_modules/next/dist/docs/` guidance required by `apps/control-plane/AGENTS.md` before writing Next.js code.
- A resolution is bookkeeping only: it must never call account-state, signup, dispatch, or AI-control services.

## Review Focus

1. Empty, whitespace-only, or 501-character notes must fail without a resolution row (Task 2 tests `test_resolve_rejects_invalid_note`; Task 3 tests `test_resolve_action_rejects_invalid_form`).
2. Unknown or malformed alert IDs must not close another alert (Task 2 test `test_resolve_unknown_or_invalid_alert_id`; Task 3 test `test_resolve_action_rejects_invalid_form`).
3. Two administrators closing the same alert concurrently must yield one success and one conflict, preserving the first actor and note (Task 2 test `test_resolve_concurrent_one_winner`).
4. A webhook retry after closure must leave the alert resolved, while a distinct fingerprint opens a new alert (Task 2 test `test_alert_retry_does_not_reopen_resolution`).
5. Unavailable or malformed backend data must show an error, never a reassuring zero-alert state (Task 3 test `test_operations_unavailable_or_malformed_backend`).

## File Map

- Create `supabase/migrations/<CLI-generated>_whatsapp_account_update_alert_resolutions.sql`: private, insert-only resolution schema, grants and policies. The timestamp is assigned by the pinned CLI, not guessed.
- Modify `apps/backend/tests/integration/conftest.py`: truncate the alert and resolution tables together so the foreign key does not break test cleanup.
- Create `apps/backend/tests/integration/test_account_update_alert_resolution_schema.py`: schema, permission, and one-resolution-per-alert checks.
- Modify `apps/backend/src/agents_factory/modules/whatsapp/alert_router.py`: authenticated list filter, summary, resolve request/response and atomic write; keep all alert-specific HTTP behavior in this focused router.
- Extend `apps/backend/tests/integration/test_account_update_alert_admin.py`: authorization, filtering, count, validation, race and retry tests.
- Replace `apps/control-plane/app/(authenticated)/operations/page.tsx`: open/resolved view, count, note form, loading/error/conflict copy.
- Create `apps/control-plane/app/(authenticated)/operations/alert-actions.ts`: validated authenticated server action and redirect outcomes.
- Modify `apps/control-plane/app/zuvel-theme.css`: alert list/form styles without unrelated layout changes.
- Create `apps/control-plane/tests/unit/operations-alerts.test.ts` and `apps/control-plane/tests/unit/operations-alert-action.test.ts`: rendering and action behavior.
- Extend `apps/control-plane/tests/e2e/fake-whatsapp-backend.mjs` and create `apps/control-plane/tests/e2e/operations-alerts.spec.ts`: one local browser flow, with no Meta connection.
- Update `docs/coexistence-progress.md` only after verification, recording exact results and remaining release gates.

### Task 1: Persist one immutable resolution per alert

**Files:** Create CLI-generated migration and schema test; modify integration `conftest.py`.

**Interfaces:** Produces `agents_factory_private.whatsapp_account_update_alert_resolutions(alert_id uuid primary key, resolved_by uuid not null, resolution_note text not null, resolved_at timestamptz not null)`; `alert_id` references the existing alert ID. Backend admin role gets `SELECT, INSERT` only; every other app/client role gets no privilege; RLS is enabled and forced.

- [ ] **Step 1: Verify the disposable database target.** Set `COEX_ALERT_SUPABASE_WORKDIR` and `COEX_ALERT_TEST_DATABASE_URL` to a separate local project, confirm its project ID and database port are not the active stack's, and check `SELECT inet_server_port()` before any migration or test. Stop if the target is ambiguous.
- [ ] **Step 2: Write failing schema tests.** In `test_account_update_alert_resolution_schema.py`, add `test_resolution_schema_restricts_roles` (forced RLS; admin SELECT/INSERT only; app, anon, authenticated, service_role denied) and `test_resolution_requires_existing_alert_and_single_note` (foreign key, unique alert ID, trimmed 1–500-character note, no UPDATE/DELETE privilege).
- [ ] **Step 3: Confirm RED.** Run `TEST_DATABASE_URL="$COEX_ALERT_TEST_DATABASE_URL" .venv/bin/pytest apps/backend/tests/integration/test_account_update_alert_resolution_schema.py -q`; expect missing-table failure, not a connection to the active port.
- [ ] **Step 4: Create the migration file.** Run `SUPABASE_TELEMETRY_DISABLED=1 ./node_modules/.bin/supabase migration new whatsapp_account_update_alert_resolutions`; record the CLI-generated path.
- [ ] **Step 5: Implement the schema.** Use `apply_patch` on that generated file for the table, foreign key, 1–500-character trimmed-note check, revoked broad grants, forced RLS, and separate admin SELECT/INSERT policies. Do not add UPDATE/DELETE grants or policies.
- [ ] **Step 6: Adapt test cleanup.** Change `conftest.py` to truncate both private tables in one statement; check the statement names exactly the existing alert and new resolution tables.
- [ ] **Step 7: Apply to the disposable project only.** Copy the new migration into that project's migrations directory and run `SUPABASE_TELEMETRY_DISABLED=1 ./node_modules/.bin/supabase migration up --local --workdir "$COEX_ALERT_SUPABASE_WORKDIR"`; confirm the new entry in that project's migration list.
- [ ] **Step 8: Confirm GREEN.** Re-run the Step 3 pytest command; expect both schema tests to pass.
- [ ] **Step 9: Check database advice.** Run `SUPABASE_TELEMETRY_DISABLED=1 ./node_modules/.bin/supabase db advisors --local --type all --level info --fail-on error --workdir "$COEX_ALERT_SUPABASE_WORKDIR"`; inspect any finding before moving on.
- [ ] **Step 10: Commit Task 1.** Stage only the generated migration, new schema test and changed integration fixture; commit as `Persist manual WhatsApp alert resolutions`.

### Task 2: Expose admin reads and one-time manual resolution

**Files:** Modify `alert_router.py` and extend `test_account_update_alert_admin.py`.

**Interfaces:** Keep `GET /admin/whatsapp/account-update-alerts` as a list with its existing unfiltered default and bounded `limit<=100`/`offset>=0`; accept optional `status: Literal["open", "resolved"] | None` and add nullable `resolved_at`, `resolved_by`, `resolution_note` to each returned alert. Add `GET /admin/whatsapp/account-update-alerts/summary -> {open_count: int}`. Add `POST /admin/whatsapp/account-update-alerts/{alert_id}/resolve` with JSON `{note: str}` and response `{alert_id, resolved_by, resolution_note, resolved_at}`. Use the existing `PlatformAdmin` and `TransactionSession` dependencies.

- [ ] **Step 1: Write failing API tests.** Add `test_alert_list_filters_without_changing_default`, `test_alert_summary_counts_only_open`, `test_resolve_requires_platform_admin`, `test_resolve_rejects_invalid_note`, `test_resolve_unknown_or_invalid_alert_id`, `test_resolve_concurrent_one_winner`, and `test_alert_retry_does_not_reopen_resolution`. Assert 401/403 for missing/non-admin authorization, 422 for invalid input, 404 for absent UUID, 409 for already closed, no fingerprint or raw payload in responses, and no account-state changes.
- [ ] **Step 2: Confirm RED.** Run `TEST_DATABASE_URL="$COEX_ALERT_TEST_DATABASE_URL" .venv/bin/pytest apps/backend/tests/integration/test_account_update_alert_admin.py -q`; expect only the new behavior tests to fail.
- [ ] **Step 3: Extend list results.** Add nullable resolution metadata to `AccountUpdateAlert` and a fixed-SQL `status` filter in `list_account_update_alerts`; default remains the current unfiltered list.
- [ ] **Step 4: Add the summary.** Define `AccountUpdateAlertSummary(open_count: int)` and its platform-admin GET route; count only alerts without a resolution row.
- [ ] **Step 5: Add one-time resolution.** Define `ResolveAccountUpdateAlertRequest(note: str)` and `AccountUpdateAlertResolution`, trim and validate the note, check alert existence, then insert with `ON CONFLICT (alert_id) DO NOTHING RETURNING`. Return 404 when absent and 409 when already resolved; write `principal.user_id`, never a client actor ID.
- [ ] **Step 6: Confirm GREEN.** Re-run the Step 2 pytest command; expect all alert API tests to pass.
- [ ] **Step 7: Check types and lint.** Run `.venv/bin/ruff check apps/backend/src/agents_factory/modules/whatsapp/alert_router.py apps/backend/tests/integration/test_account_update_alert_admin.py` and `.venv/bin/mypy apps/backend/src/agents_factory/modules/whatsapp/alert_router.py`; expect no new findings.
- [ ] **Step 8: Commit Task 2.** Stage only `alert_router.py` and `test_account_update_alert_admin.py`; commit as `Add admin alert triage endpoints`.

### Task 3: Render and resolve alerts in Operations

**Files:** Modify Operations page and theme; create alert server action and unit/browser tests; extend local fake backend; update coexistence ledger after verification.

**Interfaces:** `resolveAccountUpdateAlert(formData: FormData): Promise<void>` accepts `alertId`, `note` and explicit `confirmed=resolve`. It posts only `{note}` through `callAuthenticatedBackend`, revalidates `/operations`, and redirects with `alertResolution=resolved|conflict|invalid|error`. The page accepts `searchParams?: Promise<{ alerts?: string; offset?: string; alertResolution?: string }>`; `alerts=resolved` selects history, default selects open. It requests summary and the selected bounded list with `status` and `limit=50`, and uses `offset` for paging.

- [ ] **Step 1: Write failing unit tests.** In `operations-alerts.test.ts`, assert open count, metadata, plain-text history note/actor/time, a required note form, selected tab/paging, and `test_operations_unavailable_or_malformed_backend`. In `operations-alert-action.test.ts`, assert `test_resolve_action_rejects_invalid_form`, a single authenticated POST for valid confirmation, and distinct 409/error redirects.
- [ ] **Step 2: Confirm RED.** Run `pnpm --dir apps/control-plane exec vitest run tests/unit/operations-alerts.test.ts tests/unit/operations-alert-action.test.ts`; expect the new tests to fail on the placeholder/missing action.
- [ ] **Step 3: Implement the server action.** Read the relevant Next.js 16.3.2 local guide required by `AGENTS.md`; implement `resolveAccountUpdateAlert` with UUID, note and confirmation checks, one authenticated POST, and distinct redirect outcomes.
- [ ] **Step 4: Implement the page.** Replace the placeholder with server-side calls and local `isAlertSummary(value: unknown)` and `isAccountUpdateAlertList(value: unknown)` runtime guards; show open count, open/resolved paging, explicit error/conflict notices and the confirmed note form. Render backend text as plain text only.
- [ ] **Step 5: Style the new section.** Add focused alert list/form rules to `zuvel-theme.css`; leave unrelated page styles unchanged.
- [ ] **Step 6: Confirm unit GREEN.** Re-run the Step 2 Vitest command; expect every new unit test to pass.
- [ ] **Step 7: Add the local browser case.** Extend `fake-whatsapp-backend.mjs` with alert read/resolve responses and create `operations-alerts.spec.ts` to sign in locally, resolve one alert, and view its history without connecting to Meta.
- [ ] **Step 8: Confirm browser GREEN.** Run `pnpm --dir apps/control-plane exec playwright test tests/e2e/operations-alerts.spec.ts`; expect the local flow to pass.
- [ ] **Step 9: Check frontend quality.** Run `pnpm --dir apps/control-plane typecheck` and `pnpm --dir apps/control-plane lint`; expect no new findings.
- [ ] **Step 10: Recheck relevant backend gates.** Run `TEST_DATABASE_URL="$COEX_ALERT_TEST_DATABASE_URL" .venv/bin/pytest apps/backend/tests/integration/test_account_update_alert_admin.py apps/backend/tests/integration/test_account_update_alert_resolution_schema.py -q`, `.venv/bin/pytest apps/backend/tests/unit apps/backend/tests/contract -q`, and `git diff --check`. Run broader database/security gates only after verifying their target is disposable; otherwise record them as pending.
- [ ] **Step 11: Record evidence.** Update `docs/coexistence-progress.md` with exact results, any separately deferred Meta-reviewer failure, and remaining release gates.
- [ ] **Step 12: Commit Task 3.** Stage only the Operations files/tests, fake backend and ledger; commit as `Add Operations alert triage panel`. Do not merge, push, deploy, migrate production, or onboard a live number.

## Final Checkpoint

- [ ] Review the whole branch for permissions, secret exposure, accidental account-state effects and unrelated edits; confirm the original checkout is unchanged.
- [ ] Report test evidence and remaining blockers. Keep the release gate CLOSED until a separate, explicit pilot and production decision.
