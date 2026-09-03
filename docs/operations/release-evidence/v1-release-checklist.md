# Agents Factory v1 release checklist

Release decision: **BLOCKED — external Staging evidence required**.

This checklist is completed only for one exact Standard SME candidate. Empty or
placeholder evidence is a blocker, never a waiver.

## Exact artifacts

- [ ] Git commit SHA recorded
- [ ] Backend and Control Plane image digests recorded
- [x] Latest migration expected: `20260903170000`
- [ ] AgentSpec ID and SHA-256 digest recorded
- [ ] Knowledge version ID and SHA-256 digest recorded
- [ ] Full required suite digest, seed and Quality Gate decision ID recorded
- [ ] Staging connector health snapshot recorded

## Discovery and wizard

- [ ] Use cases, channels and expected WhatsApp volume recorded
- [ ] Processes mapped to Appointments, Orders and/or Returns & Claims
- [ ] Sources, systems, handoff surface, high-risk actions and approvers recorded
- [ ] Standard classification confirmed; unsupported requests recorded
- [ ] Responsible business, technical, privacy and incident contacts assigned
- [ ] Shared 12-step wizard completed without tenant-specific code

## Representative scenarios

- [ ] FAQ, scope redirect and Spanish/English behavior
- [ ] Order reads, confirmed writes and changed-state revalidation
- [ ] Approval and rejection; no HIGH action without approval
- [ ] Case create, deduplicate, reopen and status
- [ ] Audio, image, document, location, contact and unsupported video behavior
- [ ] Enabled/disabled handoff and no AI reply in `HUMAN_ACTIVE`
- [ ] Provider outage, duplicate webhook, retry/idempotency and uncertain write
- [ ] Abuse/safety, approved proactive template and tenant-isolation attacks

## Ten release criteria

- [ ] Consequential duplicates are impossible under replay
- [ ] Cross-tenant probes fail closed without discovery
- [ ] AI is silent while human control is active
- [ ] Every HIGH execution has approval evidence
- [ ] Approved work revalidates current state before execution
- [ ] Uncertain writes never produce a success claim
- [ ] Dependency outages remain localized
- [ ] Knowledge changes do not silently alter Production
- [ ] Tokens/costs are attributed to the correct tenant
- [ ] A reviewed Production-like failure is an anonymized regression case

## Operational readiness

- [ ] Health, alert deduplication and DLQ exercise passed
- [ ] Encrypted-secret access/rotation evidence passed
- [ ] Privacy/retention configured and legal/privacy review approved
- [ ] Isolated backup/restore and single-VPS recovery drill measured
- [ ] Staging deployment/smoke and compatible rollback drill passed
- [ ] Meta template/test number and required provider accounts are healthy
- [ ] First-conversation, cost and incident monitoring owners assigned
- [ ] Manual protected Production approver/date recorded
