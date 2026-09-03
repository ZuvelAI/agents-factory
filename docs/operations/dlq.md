# Dead-letter queue

Use the Operations page; payloads are intentionally hidden. Review topic, stable
reason, attempt count, connector health and correlation/audit evidence. Choose:

- Retry only after the cause is corrected and the operation remains idempotent.
- Resolve when reconciliation proves the intended outcome already exists.
- Discard only when policy confirms the work must never execute.

Every action requires a written reason and confirmation and is audited. Never
claim success for an uncertain write; reconcile provider state first. Escalate
growing DLQ volume as an incident.
