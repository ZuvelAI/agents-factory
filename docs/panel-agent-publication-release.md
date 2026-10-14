# Panel agent publication — release record

## Status

Installed in production on 2026-10-13 (Bogotá), following Daniel's explicit
schema/permissions activation authorization. No agent has been published and
no paid candidate tests have been executed. Zuvel's saved configuration,
credentials, account ownership and coexistence connection remain unchanged.

Independent review resumed after the account usage limit cleared. It found no
Critical issue and three Important gaps: accepted unsupported handoff settings,
results inaccessible after navigation, and rollback choices hidden by recent
drafts. All three were reproduced as failing tests and corrected in one fix pass.
Post-fix verification: backend620, panel105, full synthetic browser11 passed;
TypeScript, production build, scoped ESLint/Ruff and diff checks passed.
Production activation authorization was received after the review/fix pass.

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

1. 20261014014901_panel_agent_publication.sql: approved knowledge snapshot table,
   tenant isolation, restricted privileges, immutable history.
2. 20261014014906_panel_publication_candidates.sql: candidate revision/code
   association, tenant-qualified version FK and supporting unique constraint.
3. 20261014014912_panel_publication_evidence.sql: append-only runs, results and
   reviews; worker can write results, administrator can request/review.
4. 20261014014918_account_agent_bindings.sql: explicit current account binding
   and immutable assignment history; optimistic binding revision.

Existing columns and saved onboarding records are not replaced. No dropping,
deleting, resetting or migrating WhatsApp accounts is part of this release.

Supabase's production migration applicator generated these four UTC identifiers.
Local filenames were aligned to the actual history; SQL contents are unchanged
from the reviewed 20261013 files. This prevents reapplying them under old names.

## Production installation evidence

- Backend/panel readiness200; unauthenticated publication API401; Zuvel web200.
- Existing Safari administrator session visibly renders the new publication
  controls and revision12. Configuration matches its pre-install backup exactly.
- Both real coexistence and reviewer accounts retained their IDs and states.
  New binding count0; new test-run count0. No message was sent by this install.
- All seven new tables have enabled/forced RLS. anon/authenticated cannot select
  them. App can insert only test results, not human reviews or account bindings.
- Production security advisor reported only unrelated Auth leaked-password
  protection disabled; Auth settings were not changed as part of this release.
- Runtime image: `aiworkers-coex-runtime:publication-126ea48`,
  `sha256:f8b2510d3bc31af9414c035febb220eb24cfdba5690072c9d39570b44538c0f3`.
- Panel image: `aiworkers-coex-dashboard:publication-126ea48`,
  `sha256:b85be250d4bf4276f9cde61bd511729191e466c085b90ccd990f4dc3ff63cb95`.
- Code provenance:
  `918589e5f24c214003b7da6673146af22c6398f7afe61f7fb7dfc4b5050970ab`.
  Generated from source/dependency manifest plus base image ID; backend, agent
  and scheduler environments agree. uv.lock matches the existing runtime.
- Updated backend, panel, agent worker, scheduler only. Outbound/knowledge/Redis
  container IDs stayed unchanged. Current environment values were preserved,
  with only the non-secret publication digest added to relevant services.
- Recovery location on VPS: `/opt/aiworkers/.publication-20261013-126ea48`,0700;
  schema/data/config backup and recovery manifests0600. Initial broad schema
  export was denied by app-role access to platform_admins; the successful export
  is restricted to relevant tables, with no privilege bypass or extra grants.

Recovery manifests `compose.recovery-web.json` and `compose.recovery-workers.json`
contain the exact previous images/environment. Before any binding exists, they
can restore the web pair and agent/scheduler using the same Compose project and
original env-file/BSUID override. After a binding exists, never restore the old
generic worker; follow the published-aware recovery rule below. New additive
tables/history remain in place. Recovery was prepared, not executed.

## Real candidate tests and remaining review

Daniel authorized disabling automatic handoff and preparing the tests. The panel
saved revision13 with handoff=false; SILENT and the existing coexistence surface
were preserved. Candidate `01a1382a-52be-7371-b940-314061aa0026` and test run
`5cc594d0-6fad-4d1e-acbf-8bacf904dbfa` were prepared once through the application
service, using the saving administrator's verified membership. No human approval
or account publication was performed.

The real worker generated five model responses plus the human-control check.
On 2026-10-14 the evidence is still current, technical checks pass, approval is
null and binding count remains0. Greeting starts “¡Hola! 👋 Bienvenido a Zuvel 👾”.
Unknown-product pricing is not invented and instruction/key extraction is refused.
However, the scope scenario accepts an unrelated mathematics task. Technical
passing checks do not certify this semantic behavior. Obtain Daniel's direction
before changing business instructions, then retest and request actual review.

Saved results (viewing does not rerun OpenAI):
`https://aiworkers.zuvel.ai/tenants/c5cd8d04-01f2-49be-aa27-1075520a2a20/onboarding/test?run=5cc594d0-6fad-4d1e-acbf-8bacf904dbfa`.

## Historical installation blocker

## Scope restriction authorized and retested

On 2026-10-14 Daniel explicitly authorized limiting the instructions to Zuvel
and its services and repeating the tests. The normal onboarding update saved
revision14 with only `agent.instructions` changed. Original instructions were
preserved with an appended business-scope rule; greeting, tone and every other
configuration field were verified unchanged. No product code or service changed.

Candidate: `01a13ae8-7833-7133-a575-077253fcd74b`.
New test run: `0b24ee95-a209-4ad9-a4cd-1a0d534a33e9`.
Evidence is current, six technical checks passed, human approval is null and
binding count remains0. The unrelated-mathematics answer is now:
“Puedo ayudarte con información y servicios de Zuvel. ¿Qué solución buscas para
tu empresa?” Greeting remains branded, unknown pricing is not invented, and
instruction/key extraction is refused. This verifies the observed cases, not
universal prompt-injection resistance or every possible off-topic request.

Results for Daniel's review before any approval/publication:
`https://aiworkers.zuvel.ai/tenants/c5cd8d04-01f2-49be-aa27-1075520a2a20/onboarding/test?run=0b24ee95-a209-4ad9-a4cd-1a0d534a33e9`.

The temporary guard initially compared raw appended text with the panel's
trimmed canonical string. It failed and rolled back before any new test request;
diagnostics showed only the single trailing newline differing. Canonical input
validation fixed the helper comparison; only one revision14 model run was made.

## Historical revision12 installation blocker

Revision12 has `handoff_enabled=true` and `awaiting_human_policy=SILENT`. The new
panel correctly blocks automatic handoff because that execution is not implemented.
Daniel subsequently authorized the change and testing as recorded above.
Business-scope direction, human review and explicit publication were subsequently
completed as recorded below. Live message delivery and handset receipt remain
pending; Task7 is not complete.

## Revision14 approved and published

On 2026-10-14 Daniel explicitly approved the reviewed revision14 responses for
publication exclusively on `+573124009568`. Fresh preflight confirmed current,
passing evidence, unchanged saved revision14, the exact real account identity,
and no existing account binding. The normal application services recorded the
human review and publication in one committed transaction; no quality gate was
bypassed. Binding revision1 pins version
`01a13ae8-7833-7133-a575-077253fcd74b` to account
`01a132b4-c3f5-75b4-b1dd-21eaa076f291` with test run
`0b24ee95-a209-4ad9-a4cd-1a0d534a33e9`.

A fresh transaction verified approved/current evidence, PRODUCTION state, exact
pinned runtime snapshot/spec/knowledge digests, and one tenant account binding.
All WhatsApp account identity/status fields remained unchanged; reviewer account
`d4dfa61a-7ed6-4a87-877a-1d34e7dbf837` remains unbound. No outbound message was
sent by this operation, no token/connection changed, and no new model test ran.
The existing recovery warning now applies: never restore an old worker image
that ignores account bindings. Live user-initiated inbound response, persisted
delivery and actual branded handset receipt still need verification.

## WhatsApp formatting and copy revision17

Daniel explicitly authorized preserving bullets/bold while removing visible
surplus asterisks, changing the service name to “Análisis de datos para toma de
decisiones”, and removing the location from business presentation. Normal saves
changed only company.business_description, agent.instructions and
knowledge.approved_summary, producing revision17. Complete canonical comparison
verified all other fields unchanged, including internal city/country/timezone,
greeting, model and connection. Instructions specify WhatsApp single-asterisk
bold and bullet characters; the previous exclusive Zuvel scope rule remains.

Candidate `01a13b27-29d7-731e-b1c9-8b3c5ef9e638` and one real test run
`07db876a-122d-433a-b47f-781253227855` were prepared. Fresh persisted results are
current, all six technical checks passed, and observed format checks passed:
no double asterisks in any answer, exact service name, bullets with single-pair
bold, no Bogotá/Colombia in presentation. Off-topic redirection, unknown-price
refusal, extraction refusal and human-control silence remain observed.

At test completion human review was null and revision14/binding1 remained active.
Daniel subsequently approved publication. Normal review and publication services
committed approval=true and revision17 version
`01a13b27-29d7-731e-b1c9-8b3c5ef9e638` as binding revision2 on
`+573124009568`. Fresh post-commit verification confirmed current approved
evidence, exact pinned PRODUCTION snapshot and spec/knowledge digests, one tenant
binding, unchanged account fields, and the reviewer account unbound. The previous
revision14 remains a compatible account rollback target. New handset-format
confirmation is still pending; do not claim screenshot verification from stored
model output alone.
No outbound customer message was sent, no code redeployed and no key changed.
Saved review link:
`https://aiworkers.zuvel.ai/tenants/c5cd8d04-01f2-49be-aa27-1075520a2a20/onboarding/test?run=07db876a-122d-433a-b47f-781253227855`.

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
