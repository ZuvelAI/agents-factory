# Incident response

1. Acknowledge the deduplicated incident and assign incident/security owners.
2. Use correlation and trace IDs to identify tenant, component, exact versions
   and affected action without reading unrelated customer content.
3. Contain locally: disconnect one connector, pause promotion or isolate the VPS.
4. Reconcile uncertain writes, DLQ and human-active conversations. Preserve safety
   evidence; never export secrets or raw personal content into the incident log.
5. Recover, run targeted health/security/eval checks, resolve the incident and add
   one sanitized reviewed regression case.

Cross-tenant access, secret exposure, HIGH approval bypass and human-control
violations are hard release blockers. Disaster recovery uses the
[single-VPS runbook](../../infrastructure/runbooks/disaster-recovery.md).
