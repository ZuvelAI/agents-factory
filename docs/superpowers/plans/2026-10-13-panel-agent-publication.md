# Panel Agent Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publicar una versión comprobada del agente configurado en el panel y usarla para la cuenta WhatsApp explícitamente seleccionada, conservando borradores, datos y conexión.

**Architecture:** Proyectar la revisión del onboarding a AgentSpec y a una versión inmutable del resumen aprobado. Persistir pruebas y revisión humana ligadas a digests exactos, reutilizar el ciclo de publicación y resolver el agente por cuenta de conversación. El panel distingue guardar, probar y publicar.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, PostgreSQL/RLS, ARQ, Next.js App Router, pytest y Vitest; reutilizar dependencias y runtimes instalados.

**Spec:** `docs/superpowers/specs/2026-10-13-panel-agent-publication-design.md`

## Global Constraints

- Guardar configura un borrador; probar y publicar son acciones explícitas.
- No se cambia el número, la coexistencia, los tokens, las cuentas de revisión ni la conexión de Meta.
- El conocimiento inicial será una versión inmutable del texto/resumen aprobado, nombre de fuente, tipo, referencia, autoridad y revisión declarada.
- Una URL o un nombre de PDF solo son procedencia: no implican descarga, lectura o validación automática del documento.
- Nunca usar un borrador como respuesta real ni volver silenciosamente al proveedor genérico cuando una cuenta enlazada esté mal configurada.
- Acciones de alto riesgo que requieran enlace/OTP no se habilitan si ese flujo no existe.
- Nuevas tablas requieren RLS, claves compuestas por tenant y restricciones de inmutabilidad.
- No se envían pruebas a clientes reales sin destinatario y contenido autorizados.

## Review Focus

- Dos cuentas del mismo tenant: publicar una no modifica el agente ni permisos de la otra; Task 5/6.
- Editar mientras se prueba/publica: revisión o digest obsoletos rechazan publicación; Task 3/5.
- Referencia PDF/web sin texto aprobado: no se completa Knowledge ni se inventa contenido; Task 1/2.
- Contenido aprobado que intenta cambiar reglas: permanece contexto no confiable bajo seguridad de plataforma; Task 2/4.
- Agente enlazado sin versión íntegra: no cae al saludo genérico ni responde con otro tenant; Task 6.

## Environment and file map

Usar el worktree existente `codex/whatsapp-coexistence`, no crear otro checkout.
Los cambios previos de WhatsApp y Conversations están pendientes y se preservan;
cada commit nuevo incluye solo sus archivos. Leer AGENTS.md y skills aplicables
antes de implementación, incluyendo Supabase para esquema/RLS y Next para UI.

Backend: añadir archivos enfocados en `modules/agent_factory/` para conocimiento
manual, proyección, pruebas, revisión y enlace; no concentrarlos en onboarding.py.
Reutilizar modelos/compiler/service/repository existentes y su autorización.
UI: añadir componentes de publicación dentro de `components/onboarding/`.
Worker: resolver instancia por conversación durante cada job, en su sesión scoped.

Verificación local: venv `/private/tmp/aiworkers-timeout-tests.Pl7OOM/venv`, base
desposable `127.0.0.1:55322`, Redis `127.0.0.1:56379`; revalidar su existencia.
No ejecutar tests contra producción. Ensayar migraciones en una base desechable
nueva o respaldada; no resetear la base existente sin necesidad/autorización.

## Task 1: Versiones inmutables de conocimiento aprobado

**Files:**
- Create: `supabase/migrations/20261013180000_panel_agent_publication.sql`
- Create: `apps/backend/src/agents_factory/modules/agent_factory/approved_knowledge.py`
- Test: `apps/backend/tests/integration/agent_factory/test_approved_knowledge.py`

**Interfaces:**
- `ApprovedKnowledgeSnapshot`: id, tenant_id, digest, source_name, source_type, source_reference, authority, approved_summary, review_confirmed, created_at.
- `ApprovedKnowledgeRepository(session, context).freeze(configuration: KnowledgeConfiguration) -> ApprovedKnowledgeSnapshot`.
- `get_by_digest(digest: str) -> ApprovedKnowledgeSnapshot | None`, always tenant scoped.

- [ ] Write failing tests: reviewed, conflict-free text freezes identically once; changing text/reference/authority changes digest; empty text, unreviewed text or critical conflicts rejects; URL alone cannot complete; cross-tenant read returns none; runtime DB role cannot update/delete snapshots.
- [ ] Run `pytest apps/backend/tests/integration/agent_factory/test_approved_knowledge.py -q`; confirm failures name missing behavior, not broken fixtures.
- [ ] Add `agent_approved_knowledge_versions`: UUID id, tenant_id FK, immutable canonical JSON snapshot, SHA-256 digest, created_at; unique(tenant_id,digest), unique(tenant_id,id). Use existing role/RLS patterns, bounded fields and append-only enforcement. Hash canonical JSON using compiler conventions.
- [ ] Implement freeze/get_by_digest with validation and conflict-safe idempotency, never fetching source URLs or documents.
- [ ] Apply migration only locally; run tests and schema isolation checks. Commit only this task's changes: `feat: version approved manual agent knowledge`.

## Task 2: Proyección del onboarding hacia candidato

**Files:**
- Create: `apps/backend/src/agents_factory/modules/agent_factory/onboarding_projection.py`
- Modify: `apps/backend/src/agents_factory/modules/agent_factory/models.py`
- Modify: `apps/backend/src/agents_factory/modules/runtime/customer_service/instructions.py`
- Test: `apps/backend/tests/unit/agent_factory/test_onboarding_projection.py`

**Interfaces:**
- `project_onboarding(configuration: OnboardingConfiguration, knowledge: ApprovedKnowledgeSnapshot, code_digest: str) -> AgentSpecConfiguration`.
- Add optional immutable `approved_business_context` to configuration, default None for legacy specs; typed snapshot containing text, source and digest. Knowledge.digest must equal that snapshot digest when present.
- Existing `CustomerServiceInstructionsBuilder.build(spec=...) -> str` consumes the frozen context.

- [ ] Write failing tests: Zuvel name, saved greeting/tone/treatment/languages/vocabulary/instructions and policy notes enter projection; source/summary enter separated business-context section; malicious summary cannot remove platform safety; changed input changes compiled digest; old specs remain readable with unchanged digest (omit absent new field from legacy canonical serialization).
- [ ] Run `pytest apps/backend/tests/unit/agent_factory/test_onboarding_projection.py apps/backend/tests/unit/agent_factory/test_compiler.py -q`; verify RED.
- [ ] Map identity/persona fields deterministically; retain platform instructions first and label knowledge/persona untrusted. Honor configured languages in core instructions instead of contradicting them with an unconditional bilingual rule. Guard runtime output/token limits.
- [ ] Map capability requests only through current registry and existing validated bindings. Reject requested unsupported tools, customer identity methods or high-risk approval workflows; never grant them from free text. Handoff availability uses real existing facts, not a checkbox alone.
- [ ] Keep knowledge reference and embedded snapshot digest consistent. Unsupported settings return named blockers for the panel, not silently ignored fields.
- [ ] Run projection/compiler/schema/core-language tests; commit `feat: compile onboarding agent candidates`.

## Task 3: Preparación de candidatos y estado real del wizard

**Files:**
- Create: `apps/backend/src/agents_factory/modules/agent_factory/publication_service.py`
- Create: `apps/backend/src/agents_factory/modules/agent_factory/publication_router.py`
- Modify: `apps/backend/src/agents_factory/modules/tenants/onboarding.py`
- Modify: `apps/backend/src/agents_factory/modules/agent_factory/repository.py`
- Modify: `apps/backend/src/agents_factory/main.py`
- Test: `apps/backend/tests/integration/agent_factory/test_publication_candidates.py`

**Interfaces:**
- Admin routes under `/admin/tenants/{tenant_id}/agent-publication`.
- `GET /`: `PublicationState` (saved revision, candidates, published version, account list, explicit blockers), without secrets.
- `POST /candidates`: `{expected_revision:int}` -> candidate/version IDs and digests.
- `PanelPublicationService.prepare_candidate(expected_revision:int) -> AgentSpecVersion` uses Task 1/2 and existing create_instance/create_draft/promote_to_test.

- [ ] Write failing tests: prior config preserved; repeat same revision reuses candidate; stale expected_revision returns409; incomplete settings returns named blockers; unauthorized401/403; wrong-tenant404; saved new revision leaves existing production untouched.
- [ ] Run candidate integration tests; verify RED.
- [ ] Add candidate-to-onboarding-revision association in migration with tenant-qualified FK and uniqueness. Code digest is supplied by deployed build provenance, not user input; unavailable digest blocks publication.
- [ ] Implement candidate preparation transactionally and current state projection. Knowledge fixed blocker becomes a real snapshot condition. Dependencies remain. A draft saved after an older snapshot does not reuse old Knowledge completion.
- [ ] Keep WhatsApp connection facts separate from previous-step blockers; no reconnect requirement when healthy. State response includes all selectable account IDs/statuses, never tokens.
- [ ] Run tests; commit `feat: prepare versioned candidates from saved panel configuration`.

## Task 4: Pruebas reales, revisión y evidencia exacta

**Files:**
- Create: `apps/backend/src/agents_factory/modules/agent_factory/publication_tests.py`
- Create: `apps/backend/src/agents_factory/modules/agent_factory/publication_evidence.py`
- Modify: `apps/backend/src/agents_factory/modules/agent_factory/publication_router.py`
- Test: `apps/backend/tests/integration/agent_factory/test_publication_evidence.py`
- Test: `apps/backend/tests/unit/agent_factory/test_publication_tests.py`

**Interfaces:**
- `POST /candidates/{version_id}/tests` -> persisted test-run ID/status.
- `GET /tests/{run_id}` -> candidate digests, bounded scenarios/responses, deterministic checks, expiry and review status.
- `POST /tests/{run_id}/review`: `{approved:bool,expected_revision:int}` records admin identity, timestamp and exact digests.
- `PersistedPanelQualityGate(session,context).evaluate(agent_spec_digest:str,knowledge_digest:str,code_digest:str) -> QualityGateEvidence | None`.

- [ ] Write failing tests: missing/failed/pending/unreviewed/expired/wrong-digest evidence cannot publish; review rejection cannot pass; human approval cannot override failed deterministic integrity checks; cross-tenant read denied; injected business text cannot mutate system rules; generation failure is visible, not a passed empty response.
- [ ] Run evidence/unit tests; verify RED.
- [ ] Persist append-only test runs/reviews with tenant-qualified version FKs, digest triple, results and validity window of24hours. Configuration edits/code changes invalidate applicability immediately.
- [ ] Run six candidate scenarios (brand greeting, known fact, unknown information, unrelated request, injection attempt, human-control behavior) with current runtime adapter, frozen context, no customer delivery and no state-changing tools. Bound concurrency/timeouts/output; record failures explicitly. Do not use smoke runner alone as production approval.
- [ ] Deterministic validation verifies schema, matching digests, tenant identity, allowed tools and proven human-control handling. Administrator reviews displayed generated answers; approval is explicitly human evidence, not claimed automated correctness. Persisted gate requires both passing checks and current human approval.
- [ ] Audit test requests/reviews; no secrets or internal safety prompt in responses/logs. Run tests; commit `feat: persist reviewed agent publication evidence`.

## Task 5: Publicación y asignación explícita por cuenta

**Files:**
- Create: `apps/backend/src/agents_factory/modules/agent_factory/channel_binding.py`
- Modify: `apps/backend/src/agents_factory/modules/agent_factory/publication_service.py`
- Modify: `apps/backend/src/agents_factory/modules/agent_factory/publication_router.py`
- Modify: `apps/backend/src/agents_factory/modules/agent_factory/service.py`
- Test: `apps/backend/tests/integration/agent_factory/test_channel_publication.py`

**Interfaces:**
- `POST /publish`: `{version_id:UUID,whatsapp_account_id:UUID,expected_revision:int,test_run_id:UUID}` -> published version/binding.
- `POST /rollback`: `{whatsapp_account_id:UUID,target_version_id:UUID,expected_binding_revision:int}`.
- `AccountAgentBindingRepository(session,context).get_for_account(account_id:UUID) -> AccountAgentBinding | None`.

- [ ] Write failing tests: atomic publish+binding; unreviewed/stale candidate denied; unhealthy/inactive account denied; two same-tenant accounts remain isolated; cross-tenant FK denied; concurrent publications produce one accepted revision; rollback only compatible previously published target; old knowledge/history preserved.
- [ ] Run channel tests; verify RED.
- [ ] Add tenant-qualified current binding plus append-only binding history; row lock and revision checks guard publication races. Gate and revision validated again inside transaction. Use existing lifecycle transition/audit records with persisted evidence, not bypasses.
- [ ] Require exact account selection; never auto-pick reviewer account. Enforce compile/test/gate/production transitions and safe rollback without modifying WhatsApp credentials or Meta subscription.
- [ ] Run lifecycle/channel tests; commit `feat: bind reviewed production agents to WhatsApp accounts`.

## Task 6: Resolver publicado por conversación en el worker

**Files:**
- Create: `apps/backend/src/agents_factory/modules/agent_factory/channel_provider.py`
- Modify: `workers/agent-worker/src/agent_worker/jobs.py`
- Modify: `apps/backend/src/agents_factory/modules/agent_factory/repository.py`
- Test: `apps/backend/tests/integration/runtime/test_channel_agent_turn.py`

**Interfaces:**
- `ConversationAgentSpecProvider(session,context,conversation_id,legacy_provider)` implements existing `get_active(tenant_id:UUID) -> AgentSpecSnapshot | None`.
- Resolve conversation.whatsapp_account_id with tenant filter, then Task5 binding and ProductionAgentSpecProvider. Validate snapshot/knowledge digests before response.

- [ ] Write failing tests: published Zuvel context reaches runtime; separate account receives its own agent; legacy unbound account unchanged; bound missing/corrupt version fails closed without generic fallback; draft edit does not change published turn; human-controlled conversation remains silent; in-flight snapshot remains unchanged after publish.
- [ ] Run channel-turn tests; verify RED.
- [ ] Construct scoped provider within each agent-turn job's DB session, not one mutable global provider. Preserve explicit injected providers for tests, conversation lock, idempotency and current runtime/tool policy boundaries.
- [ ] For linked account use only verified PRODUCTION; do not silently degrade. Fetch immutable context by matching digest. Audit selected version ID/digest without logging prompt or customer text.
- [ ] Run runtime/worker/outbound regression tests; commit `feat: use published account agent snapshots for WhatsApp turns`.

## Task 7: Panel probar/publicar, despliegue y verificación completa

**Files:**
- Create: `apps/control-plane/components/onboarding/agent-publication.tsx`
- Create: `apps/control-plane/components/onboarding/agent-publication-actions.ts`
- Modify: `apps/control-plane/components/onboarding/step-form.tsx`
- Modify: `apps/control-plane/app/(authenticated)/tenants/[tenantId]/onboarding/[step]/page.tsx`
- Test: `apps/control-plane/tests/unit/agent-publication.test.ts`
- Create: `docs/panel-agent-publication-release.md`

**Interfaces:**
- `AgentPublication` consumes backend PublicationState and renders prepare/test/review/publish/rollback actions. Server actions preserve current admin authorization and revision/digest checks.

- [ ] Write failing UI tests: clear draft vs published; Knowledge manual-summary notice; unhealthy account cannot publish; no account auto-selected; saved step persists; stale revision error visible; test generation error distinguishable from success; source text escaped; failed gate cannot be marked complete manually.
- [ ] Run scoped Vitest test; verify RED.
- [ ] Implement controls on Test/Quality Gate/Production and state summary on WhatsApp; display candidate/active revisions, selected account, six answers, review decision and exact publication confirmation. Render unsupported requirements as blockers. Keep existing form data; do not auto-publish when navigating.
- [ ] Run backend and worker full test suites in isolated local environment, frontend suite/typecheck/lint/build, RLS migration tests, format and git diff check. Document every excluded historical gate and warning rather than claiming an unfiltered green suite.
- [ ] Verify authenticated browser flow using synthetic tenant/config: save→prepare→test→review→publish; edit leaves current version unchanged; negative cross-tenant/account cases and rollback. Restore fixture-only changes afterwards.
- [ ] Before production: inventory live DB migration state/services/build provenance, backup relevant data, prepare service rollback and scoped additive migration. No blind schema reset. Activate only backend/panel/agent-worker affected by this release; preserve outbound sender fix and other current changes.
- [ ] Confirm health and authorized panel read/write flow. Daniel reviews Zuvel's saved settings and candidate answers before its explicit production publish. Only then run one authorized real WhatsApp test; require persisted SENT/DELIVERED and handset receipt with appropriate brand response. Delivery ACCEPTED alone is insufficient.
- [ ] Record active version/binding, migrations/images, evidence and rollback steps in release note. Commit scoped UI/tests/docs: `feat: manage reviewed agent publication from the panel`.

## Self-review completed

Spec sections map to Tasks1–7; exclusions remain explicit. All five Review Focus
conditions have named tests. New interfaces are defined at their owning tasks;
later tasks reuse them. No implementation, database migration or production
configuration change is authorized merely by writing this plan. Execution starts
after Daniel reviews the plan and chooses the method.
