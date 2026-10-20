# Conversations read view — 2026-10-13

Owner approved replacing the provisional Conversations page with authenticated,
tenant-scoped read-only conversation and message views, and deployment.

Added two GET endpoints under /admin/tenants/{tenant_id}/conversations, requiring
the existing PlatformAdmin dependency. Explicit tenant filters on conversations
and messages, bounded limit/offset, stable ordering and 404 for a conversation
outside the selected tenant. Responses exclude raw payloads, vault references and
credentials. Message projection exposes text only; media stays a type placeholder.
No mutation endpoint, schema migration, sending control or agent activation.

Page now reads tenants, selected tenant conversations and explicitly selected
conversation messages with the existing server-side authenticated helper. Client
selection is checked against the authorized tenant list and conversations against
the current page. Runtime shape validation, escaped text, separate failure/empty
states, pagination, refresh link and Spanish status labels.

Tests: observed missing GET route return 404 before implementation. Integration
test covers tenant scoping, message display, cross-tenant 404, bounded limit and
unauthenticated 401. Five frontend tests cover visible saved messages, escaping,
error vs empty and malformed/unlisted selections. Latest verification: 571 backend
tests passed with one dependency deprecation warning; historical reset/canonical
environment files excluded as previously documented. 93 panel tests, typecheck,
ESLint and Ruff passed. Initial verification had Redis unavailable and a test
parameter name matching the credential scanner; both resolved without loosening
the scanner or modifying production data.

Deployed images aiworkers-coex-runtime:conversations-20261012 and
aiworkers-coex-dashboard:conversations-20261012. Backend extends the sender-fix
image, replacing only tenants/admin_router.py. Panel builds from the retained
release source with the new page and tests. Locked build passed. Same web container
names, environments, ports, network and commands. Workers and Redis untouched.
Rollback configuration (mode 600):
/opt/aiworkers/.conversations-20261012/compose.before-conversations.json.

Both web services healthy after cutover. Owner-authenticated Safari live check:
conversation appears on /conversations; Ver mensajes displays prueba Zuvel 4,
later test messages and recorded outbound agent text. This establishes the read
view, not delivery of every response to the recipient's phone. No synthetic
message or credential exposed during browser verification.
