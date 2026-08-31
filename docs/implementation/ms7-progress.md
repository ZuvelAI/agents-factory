# MS7 — Control Plane Operational UX

## Authorization and product direction

MS6 was explicitly approved by the user. This branch builds on its accepted
technical checkpoint while retaining the documented live-provider/production gates.
The next approved dependency is Task 36 (Usage Foundation), followed by Tasks 37–43
for the Control Plane. No Superpowers workflow or master-plan rewrite is used.

Agents Factory remains a reusable, tenant-configured framework. The wizard owns
Company → Agent → Capabilities → Integrations → Knowledge & Conflict Review →
Policies & Identity → Human Operations → Approval Routes → WhatsApp → Test →
Quality Gate → Production, with resumable progress and explicit blockers.
SDK/runtime details remain behind the platform boundary. Standard client onboarding
must not require rebuilding the product or routine editing of code/YAML/SSH.

Task 36 is in progress; MS7 and production readiness are not yet accepted.

## Task 36 — ledger, pricing and policy-decision checkpoint

- Implemented a provider-neutral tenant usage ledger with opaque provenance,
  idempotent concurrent recording, conflicting-replay rejection and tenant-scoped
  reference checks. Missing measurements/prices remain unknown rather than zero.
- Effective-date price versions and saved snapshots preserve historical costs;
  Decimal pricing separates cached input and includes reasoning within output.
  Provider-reported costs, WhatsApp metadata and storage/infrastructure units have
  explicit contracts. No live provider prices or credentials are assumed.
- Added revision-checked admin configuration and bounded cost summaries by tenant,
  run, conversation, Action, Case, model and kind. Currency separation, unknown-cost
  flags, null attribution groups and explicit partial-data/truncation flags avoid
  presenting incomplete data as a complete operational report.
- Commercial quota decisions distinguish 70/85/100 alerts and grace/overage from
  independent hard-limit decisions. These new decisions are not yet wired into
  actual runtime/queue execution or distributed capacity reservation.
- Added two FORCE-RLS tables with least-privilege grants and immutable usage history.
  Supabase/Postgres guidance informed isolation, indexing and short transactions.

Seven focused checks passed: two pricing/policy cases, two local attribution/
configuration cases, the two new-table RLS matrices and registry completeness.
Initial failures were confined to missing actor IDs in new fixtures and a UUID/text
parameter conflict in the new matrix insert. Only those three cases were retried;
the four passing cases and all old suites were not rerun. Ruff/mypy passed and local
Supabase advisors found no issues. No live API, dependency upgrade, browser suite
or full regression run was used.

Captured `20260831183315_usage_costs.sql`, preserving FORCE RLS and explicit
revocations omitted by the schema diff. The previous MS6 migration also replayed
successfully in the disposable schema-capture database; no MS6 test was rerun.

Next: producer instrumentation, atomic concurrency/rate limits, persisted quota
alerts and runtime/queue/tool enforcement, followed by the new end-to-end anomaly
scenario. The pure loop decision check here is not represented as that end-to-end
acceptance. See `docs/usage.md` for composition and limitations. Task 36 remains open.
