# Agents Factory v1 test report

Report state: **implementation evidence prepared; release not authorized**.

## Candidate identity

The exact commit, images, AgentSpec, Knowledge and Quality Gate decision will be
filled by the Staging workflow. Until all are present and mutually matching, prior
passing evidence is stale by definition and Production remains blocked.

## Evidence available in the repository

- Versioned global, security, tenant-isolation, human-control, failure-handling,
  capability, runtime-smoke and release-acceptance eval suites.
- Exact-digest persisted Quality Gate with seven unconditional hard blockers and
  non-zero local CLI behavior.
- Tenant-scoped trace/metric/health/incident records with payload redaction.
- Durable privacy jobs, retention defaults, legal hold and key-rotation procedure.
- Non-root versioned images, Staging/Production workflows, protected Production
  environment boundary, smoke and rollback entrypoints.
- Checksummed backup/Storage/config/image/external-mapping inventory and isolated
  restore verifier.

## Evidence intentionally pending

These items require configured external systems and were not fabricated:

| Blocker | Required evidence | Owner |
| --- | --- | --- |
| Representative Standard tenant | Completed Discovery and wizard screenshots/IDs | Platform admin |
| Meta | Test number, approved template, webhook/send receipts | Integration owner |
| Google/WooCommerce | OAuth/API sandbox health and representative operations | Integration owner |
| Staging | Immutable image deploy, smoke, outage isolation and rollback timestamps | Operations owner |
| Restore | Disposable Supabase/VPS drill with measured RPO/RTO | Operations owner |
| Privacy/legal | Jurisdiction-specific approval and provider deletion receipts | Privacy owner |
| Release approval | Exact passing checklist signed with approver/date | Release owner |

## Decision

`BLOCKED_EXTERNAL_EVIDENCE`. This is the required safe outcome: no aggregate score
or local deterministic test may waive a missing critical provider, privacy,
restore, rollback or exact-version artifact check. When the checklist is complete,
the protected GitHub Production environment remains the final manual action.
