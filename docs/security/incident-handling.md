# Security incident handling

Incidents are distinct from logs, metrics, traces and audit events. Each signal
has a tenant, correlation ID, stable type, severity, bounded summary and evidence
retention deadline. Repeated symptoms share a fingerprint and increment one open
incident rather than generating notification storms.

CRITICAL symptoms—including cross-tenant evidence, approval bypass or secret
exposure—block release and require the security owner. Operators preserve
sanitized evidence, isolate the affected tenant or connector, rotate exposed
credentials, reconcile uncertain writes and record containment/recovery. Raw
customer content and secrets never enter tickets or logs. See the
[incident-response procedure](../operations/incident-response.md).
