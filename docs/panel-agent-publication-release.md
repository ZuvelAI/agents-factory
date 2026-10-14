# Panel agent publication — release record

## Status

Local implementation is ready for independent review. Production has NOT been
migrated, deployed or published by this work. Zuvel's saved configuration,
credentials, account ownership and coexistence connection remain unchanged.

Independent review resumed after the account usage limit cleared. It found no
Critical issue and three Important gaps: accepted unsupported handoff settings,
results inaccessible after navigation, and rollback choices hidden by recent
drafts. All three were reproduced as failing tests and corrected in one fix pass.
Post-fix verification: backend620, panel105, full synthetic browser11 passed;
TypeScript, production build, scoped ESLint/Ruff and diff checks passed.
Production activation authorization remains outstanding.

Deferred Minor findings: concurrent approve/reject can produce a uniqueness
error (no gate bypass); result UI lacks the complete timestamp/digest presentation
although backend evidence is persisted and checked. These are not silently fixed.

Implementation: approved-summary knowledge versions; deterministic onboarding
projection; preparation, durable background tests, immutable human review;
exact-digest production gate; account-specific publication/rollback; per-turn
published snapshot resolution; panel controls and real wizard states.

The model consumes approved manual summary text, not a downloaded PDF or website.
Operational capabilities without real bindings remain blocked and are explained
in the panel. Internal operator/approver contacts are not automatically injected
into customer context. No live OpenAI test request has been made during local
verification; Daniel authorized reuse of the existing key for actual panel tests.

## Local verification

- Backend baseline: 577 passed. Final post-review local run: 620 passed.
- Panel: 105 unit tests passed; TypeScript passed; production build passed.
- Full synthetic browser suite: 11 passed, including authentication and existing
  WhatsApp controls. Scoped ESLint and Ruff check passed; git diff check passed.
- Authenticated browser flow with synthetic local services: save → prepare →
  test → approve → explicitly publish → edit → existing connection/active version
  preserved. This checks UI interaction; database/runtime behavior is separately
  covered by actual local PostgreSQL integration tests.
- Local migrations applied only to disposable database port55322, not production.
- Installed Supabase CLI security advisors on explicit localhost database URL:
  no issues found. Local disposable PostgreSQL requires sslmode=disable; the
  first TLS-default connection was rejected without executing the audit.
- One existing Starlette/AnyIO deprecation warning remains.
- Historical DB gates excluded as before: test_database_gates.py,
  test_tenant_isolation_matrix.py, test_secret_tenant_isolation.py. Do not claim an
  unfiltered green backend suite.
- Full mypy currently reports two existing errors in whatsapp/history_sync.py
  at239 and315 (object→int and Any→UUID return). That file is unchanged from the
  implementation base; new publication interfaces have no remaining mypy errors.

## Migrations

1. 20261013201305_panel_agent_publication.sql: approved knowledge snapshot table,
   tenant isolation, restricted privileges, immutable history.
2. 20261013204233_panel_publication_candidates.sql: candidate revision/code
   association, tenant-qualified version FK and supporting unique constraint.
3. 20261013212835_panel_publication_evidence.sql: append-only runs, results and
   reviews; worker can write results, administrator can request/review.
4. 20261013214403_account_agent_bindings.sql: explicit current account binding
   and immutable assignment history; optimistic binding revision.

Existing columns and saved onboarding records are not replaced. No dropping,
deleting, resetting or migrating WhatsApp accounts is part of this release.

## Activation preflight and recovery

Before production schema/activation: obtain approval for the security-sensitive
database permissions/schema change, inspect migration state, take a restricted
backup of relevant schema/data and save current compose/image/settings metadata
without exposing environment values. Build with existing pinned dependencies.

Set AGENT_PUBLICATION_CODE_DIGEST to a SHA-256 build provenance digest derived
from the exact runtime source/dependency manifest, consistently in backend and
agent worker. It is not a user-entered field. A missing/mismatching digest blocks
candidate publication and linked-agent execution, never falls back silently.

Affected services: backend, panel, agent-worker and scheduler (one new test-job
topic mapping). Preserve the current BSUID sender fix, outbound/knowledge workers,
Redis, reviewer account, tokens, app ownership and existing Meta webhooks.
Public readiness and authenticated routes must be checked after activation.

Additive schema can stay in place if web services need rollback. Do not drop new
history tables to roll back code. Before first account publication, restoring the
saved images/config is sufficient. After an account has a binding, never roll the
agent worker back to a legacy image that ignores bindings and would respond
generically: stop its processing until a compatible published-aware image is
restored, or use validated account-level rollback with compatible code.

Daniel must inspect the saved Zuvel settings and actual generated candidate
answers before its explicit publication. No account is automatically selected.
Only after that: one authorized live inbound/outbound check, persisted delivery
state and handset receipt with correct brand response. ACCEPTED alone is not
delivery evidence. Record deployed image hashes, code digest, migration execution,
selected account/version and recovery location here after those steps occur.
