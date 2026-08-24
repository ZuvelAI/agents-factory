# Agents Factory v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, strictly inside the currently authorized milestone. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Agents Factory v1 so a standard SME tenant can be configured, tested, promoted, operated, and reviewed end-to-end for WhatsApp customer service without tenant-specific product code.

**Architecture:** Build one private monorepo containing a Next.js Control Plane and a Python/FastAPI modular monolith whose API, ARQ workers, and scheduler run as separate Docker Compose processes. Supabase PostgreSQL/RLS/pgvector/Storage is the durable source of truth; Redis coordinates async work and per-conversation ordering; OpenAI Agents SDK is isolated behind an internal runtime protocol so deterministic services retain control of identity, authorization, confirmation, approval, action state, and tenant isolation.

**Tech Stack:** Next.js + TypeScript; Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy async; Supabase CLI migrations; OpenAI Agents SDK for Python; `gpt-5.6-luna` with reasoning effort `low`; Supabase PostgreSQL/RLS/pgvector/Auth/Storage; Redis + ARQ 0.28.x; `gpt-4o-mini-transcribe` for voice-note transcription; Vitest/Testing Library/Playwright; pytest/pytest-asyncio/Hypothesis; Docker Compose; GitHub Actions; Hostinger VPS.

## Global Constraints

- The master specification is authoritative; its v1 decisions are approved and frozen unless the user deliberately reopens one.
- Initial product: `Agent Customer Service`; do not implement a second commercial agent product.
- “Hermes” is neither a commercial product name nor a runtime component and must not appear in executable product naming or Control Plane copy.
- Architecture: multi-tenant modular monolith with asynchronous workers; do not introduce microservices or multi-runtime orchestration.
- Runtime: OpenAI Agents SDK for Python behind the internal `AgentRuntime` boundary.
- Model baseline: `gpt-5.6-luna`, reasoning effort `low`; do not add model routing without production eval/cost evidence.
- Channel: Meta WhatsApp Cloud API through `WhatsAppProvider`; response modality is text only.
- Languages: Spanish and English; default locale `es-CO`.
- Data: shared Supabase PostgreSQL with `tenant_id`, tenant-scoped repositories, RLS, pgvector, and Storage.
- Compute: one Hostinger VPS and Docker Compose; v1 does not claim high availability.
- Queue: Redis coordinates work, locks, limits, and queues; durable business state is persisted in PostgreSQL before enqueue.
- Control Plane access: private application with the single v1 role `platform_admin`.
- Configuration lifecycle: `DRAFT → TEST → QUALITY_GATE → PRODUCTION`; Production AgentSpec versions are immutable.
- Default retention: conversation content 90 days; detailed traces 30 days; action/audit records 12 months.
- Default case timing: resolved cases auto-close after 72 hours; Live Human Handoff inactivity closes after 12 hours.
- Default Response Targets: LOW 48 hours, NORMAL 24 hours, HIGH 4 hours, CRITICAL 30 minutes.
- Consequential writes are idempotent and fail closed; `UNCERTAIN` never produces a success claim.
- High-risk actions require customer confirmation, backoffice approval, and a configured approval route.
- No tenant-specific conditionals in core. Customer-exclusive code, if ever approved, belongs to a versioned Tenant Extension.
- Do not build the excluded v1 features listed in “Scope Exclusions” below.
- Pin dependency versions in `uv.lock` and `pnpm-lock.yaml`; never install from floating versions in CI or Production.
- Before implementing Supabase or OpenAI SDK/API work, recheck the current official changelog/docs for the exact pinned versions and record relevant breaking changes in the task’s commit/PR evidence.
- Do not place production customer data in Development or Staging; secrets are environment-specific and never enter the repository, prompts, traces, or client bundles.

---

## Plan Review Gate

This revised plan and the dated v1 scope amendment in the master specification are the only project artifacts changed during this review. Do not initialize Git, create the GitHub repository, scaffold applications, install dependencies, or run migrations until the user explicitly approves starting implementation.

Plan approval is not blanket authorization to execute every task. The first implementation authorization covers **Phase 0 plus Milestone 1 only**. Each later milestone requires its own explicit user authorization after the preceding milestone review package has been accepted.

## Milestone Execution and Review Protocol

1. Execute only the currently authorized milestone (Phase 0 is bundled with the first Milestone 1 authorization).
2. Within that boundary, independent tasks may run in parallel, but no task from a later milestone may start.
3. At milestone completion, run every applicable milestone gate and present: commands and results; acceptance-criteria demonstration; exact commit/PR and artifact identifiers; architecture deviations; known risks or debt; and a recommendation to continue or correct.
4. Stop after presenting the review package. Do not begin the next milestone until the user explicitly approves it.
5. Roadmap notes about technically safe overlap describe dependency options only; they do not authorize concurrent milestone execution unless the user expressly approves both milestones.
6. Production promotion remains a separate external approval even after all implementation milestones are accepted.

## Source of Truth

- Current local source: `Agents Factory — Master Product and Architecture Design Specification.txt` (read in full on 2026-08-12 and amended on 2026-08-14 only to defer Generic REST to v1.1).
- The implementation’s first documentation commit will move it, preserving the approved 2026-08-14 amendment and every other technical decision, to `docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md` and update only the stale approval metadata so the repository reflects the user’s explicit approval.
- `Agents Factory Client Onboarding Playbook.pdf` remains a supporting operational source and is committed privately with the canonical specification.

## Scope Exclusions

The v1 plan contains no implementation task for: a full client portal; an Agents Factory human inbox; subscription billing or payment collection; multiple commercial agent products; multi-runtime support; advanced multi-agent orchestration; Shopify; Salesforce; HubSpot without a real launch requirement; the generic REST API/Webhook connector foundation (deferred to v1.1); simultaneous room/equipment/professional booking constraints; automatic refunds or credits; voice responses; advanced video understanding; a full WhatsApp template editor; dedicated enterprise infrastructure; or high-availability multi-node runtime.

Planned/unavailable connectors, including Generic REST, may be displayed as “coming later” in the Integration Catalog, but no executable adapter, auth flow, background sync, webhook, client, or hidden route is created for them in v1.

## Implementation Decisions Closed by This Plan

### Worker framework

Use **ARQ 0.28.x** because its asyncio-native worker model fits FastAPI and provides Redis queues, unique job IDs, bounded retries, deferred jobs, health keys, timeouts, and graceful completion controls. Configure an explicit JSON serializer/deserializer for typed `JobEnvelope` payloads instead of ARQ's default pickle serializer. Reliability does not depend on Redis retention: `outbox_jobs`, `job_attempts`, and `dead_letter_jobs` in PostgreSQL record intent and outcome; a scheduler reconciles pending outbox rows into ARQ; workers receive opaque durable job IDs and reload tenant-scoped state before execution.

### Speech-to-text

Use **`gpt-4o-mini-transcribe`** through the file Transcriptions API behind `SpeechToTextProvider`. It supports the required voice-note path and multilingual transcription while costing less than `gpt-4o-transcribe`; product/business vocabulary is supplied as transcription context. Benchmark Spanish/English WhatsApp fixtures for word error rate, p50/p95 latency, and cost before accepting Task 27. OpenAI API inputs/outputs are not used for training by default, but eligible API content may be retained in abuse-monitoring logs for up to 30 days; confirm the applicable endpoint/account retention and Zero Data Retention eligibility during the pre-production privacy review. Store the original tenant-scoped media and normalized transcript with provenance; never treat the transcript as authenticated identity evidence.

### Image normalization

Use **`gpt-5.6-luna` image input** behind a separate `ImageObservationProvider`, with a schema-constrained prompt that returns only normalized observations needed by the active business workflow. This media path receives no runtime tools, conversation authority, credentials, or action-execution ability; it does not turn the Agent Runtime into a universal media processor. Video remains storage-plus-metadata for human review only.

### Database access and RLS

The browser uses Supabase Auth only for the private Control Plane and calls FastAPI for product data. Backend requests verify the Supabase JWT, require `app_metadata.platform_role = "platform_admin"`, and open database transactions with an explicit `TenantContext`. Tenant workers use a non-`BYPASSRLS` application role plus transaction-local `app.tenant_id`; cross-tenant platform views use a separately credentialed non-`BYPASSRLS` admin role. Migration ownership credentials and Supabase service credentials are never used by request repositories.

### Monorepo package management

Use `uv` for Python workspaces and `pnpm` for TypeScript workspaces. Root `Makefile` targets provide stable human/CI commands while lockfiles remain the deployable dependency source.

## Architecture Contracts

The following names and signatures are fixed across tasks so independently implemented modules interoperate.

```python
@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: UUID
    actor_id: UUID | None
    actor_type: Literal["platform_admin", "customer", "system", "approver"]
    correlation_id: UUID

class AgentRuntime(Protocol):
    async def run(
        self,
        *,
        spec: AgentSpec,
        turn: AgentTurnInput,
        tools: Sequence[RuntimeTool],
    ) -> AgentTurnResult:
        raise NotImplementedError

class WhatsAppProvider(Protocol):
    def verify_signature(self, *, raw_body: bytes, signature: str) -> bool:
        raise NotImplementedError
    async def send_text(self, request: OutboundTextRequest) -> ProviderMessageResult:
        raise NotImplementedError
    async def send_template(self, request: OutboundTemplateRequest) -> ProviderMessageResult:
        raise NotImplementedError
    async def download_media(self, media_id: str) -> DownloadedMedia:
        raise NotImplementedError

class Connector(Protocol):
    @property
    def supported_operations(self) -> frozenset[str]:
        raise NotImplementedError
    async def execute(
        self, *, context: TenantContext, request: ConnectorRequest
    ) -> ConnectorResult:
        raise NotImplementedError

class KnowledgeRepository(Protocol):
    async def retrieve(
        self, *, context: TenantContext, query: KnowledgeQuery
    ) -> list[KnowledgeHit]:
        raise NotImplementedError

class SpeechToTextProvider(Protocol):
    async def transcribe(
        self, *, context: TenantContext, media: StoredMedia
    ) -> TranscriptResult:
        raise NotImplementedError

class ImageObservationProvider(Protocol):
    async def observe(
        self,
        *,
        context: TenantContext,
        media: StoredMedia,
        observation_schema: type[BaseModel],
    ) -> ImageObservationResult:
        raise NotImplementedError
```

```python
class ConversationControlState(StrEnum):
    AI_ACTIVE = "AI_ACTIVE"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    CLOSED = "CLOSED"

class AgentConfigurationState(StrEnum):
    DRAFT = "DRAFT"
    TEST = "TEST"
    QUALITY_GATE = "QUALITY_GATE"
    PRODUCTION = "PRODUCTION"

class ActionState(StrEnum):
    REQUESTED = "REQUESTED"
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    EXPIRED = "EXPIRED"
    HANDED_OFF = "HANDED_OFF"
```

```python
class IdentityLevel(IntEnum):
    UNKNOWN = 0
    WHATSAPP_RECOGNIZED = 1
    ADDITIONAL_VERIFICATION = 2
    STRONG_VERIFICATION = 3

class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class CaseState(StrEnum):
    OPEN = "OPEN"
    AWAITING_INFORMATION = "AWAITING_INFORMATION"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    DUPLICATE = "DUPLICATE"
```

All IDs are UUIDs generated server-side. All externally visible timestamps are timezone-aware UTC ISO 8601 values; tenant locale/timezone affects presentation and business calendars, not storage.

## Target File Map

```text
agents-factory/
├── .github/workflows/{ci,deploy-staging,deploy-production}.yml
├── apps/
│   ├── backend/
│   │   ├── pyproject.toml
│   │   ├── src/agents_factory/
│   │   │   ├── {main,config,database,dependencies}.py
│   │   │   ├── common/{context,ids,errors,audit,outbox,security}.py
│   │   │   └── modules/
│   │   │       ├── tenants/                 # tenants and platform administration
│   │   │       ├── agent_factory/           # AgentSpec versions and deployments
│   │   │       ├── runtime/                 # runtime protocol and OpenAI adapter
│   │   │       ├── whatsapp/                # Meta provider, webhooks, templates
│   │   │       ├── conversations/           # messages and control state
│   │   │       ├── capabilities/            # manifests, tools, gating
│   │   │       ├── knowledge/               # sources, ingestion, RAG, versions
│   │   │       ├── integrations/            # connector catalog and bindings
│   │   │       ├── policies/                # risk and action policy
│   │   │       ├── identity/                # identity assurance
│   │   │       ├── approvals/               # routes, OTP, decisions
│   │   │       ├── handoffs/                # live-human gating/state
│   │   │       ├── cases/                   # case lifecycle/targets
│   │   │       ├── media/                   # normalization and evidence
│   │   │       ├── usage/                   # costs and guardrails
│   │   │       ├── observability/           # traces, health, incidents, DLQ
│   │   │       ├── evals/                   # quality-gate service
│   │   │       └── secrets/                 # encryption envelope and redaction
│   │   └── tests/{unit,integration,contract,security}/
│   └── control-plane/
│       ├── package.json
│       ├── app/(authenticated)/             # canonical private navigation
│       ├── app/approval/[token]/            # public temporary approval surface
│       ├── components/
│       ├── lib/{api,auth,schemas}.ts
│       └── tests/{unit,e2e}/
├── workers/
│   ├── agent-worker/src/agent_worker/worker.py
│   ├── knowledge-worker/src/knowledge_worker/worker.py
│   ├── outbound-worker/src/outbound_worker/worker.py
│   └── scheduler/src/scheduler/worker.py
├── packages/
│   ├── agent-spec/{agent_spec.schema.json,README.md}
│   ├── integrations/{connector.schema.json,README.md}
│   └── shared-schemas/{events.schema.json,README.md}
├── supabase/{config.toml,migrations,seed,policies,tests}
├── evals/{cases,results,graders.py,case_schema.py,run_local.py,README.md}
├── infrastructure/{docker,proxy,scripts,runbooks}
├── docs/{architecture,capabilities,integrations,security,operations,superpowers}
├── .env.example
├── docker-compose.yml
├── Makefile
├── package.json
├── pnpm-workspace.yaml
├── pyproject.toml
└── README.md
```

Directories are created only by the first task that owns a deliverable within them.

## Dependency-Ordered Roadmap

| Phase | Milestone | Depends on | Independently demonstrable outcome |
|---|---|---|---|
| 0 | Repository and approved baseline | Plan approval | Private GitHub monorepo connected to this local folder with approved sources committed |
| 1 | M1 Platform Foundation | Phase 0 | Authenticated platform shell, tenant schema, audit/outbox conventions, cross-tenant RLS gate, Secrets Foundation, and required basic CI |
| 2 | M2 Messaging Runtime | M1 | A signed, deduplicated WhatsApp inbound event reaches an ordered agent worker, produces an observable text response, and runs through Eval Runner v0 |
| 2 | M3 AgentSpec and Policies | M1, M2 runtime boundary | Versioned AgentSpec plus deterministic identity, risk, confirmation, approval prerequisites, and action lifecycle |
| 3 | M4 Knowledge | M1, M3 versioning | Tenant-scoped structured facts and RAG sources move through proposal/review to an immutable Test candidate and answer with provenance; Production stays gated until M8 |
| 3 | M5 Connectors and Capabilities | M2, M3, M4 contracts | Appointments, Orders, and Returns & Claims execute only operations declared by initial connectors |
| 4 | M6 Cases, Approvals, Human Operations | M2, M3, M5 | High-risk requests, cases, approvals, and live handoff obey separate deterministic state machines |
| 4 | Usage foundation | M1–M6 event sources | Tenant-attributed cost and guardrail APIs are ready before dashboards consume them |
| 4 | M7 Control Plane Operational UX | M1–M6 APIs + usage foundation | A platform admin configures, tests, reviews, and operates a tenant without YAML or SSH; the last two onboarding steps show honest M8 blockers |
| 5 | M8 Quality, Hardening, Production | M1–M7 | Critical evals gate immutable Production publishing; hardened CI/CD, restore, privacy, observability, and go-live checks pass |

M2 and early M4 data work are dependency-safe after M1, but M4 publication must use M3 version contracts. M7 screens may be delivered vertically with their owning APIs, but M7 is not accepted until the complete navigation and onboarding flow is coherent. These dependency notes do not override the Milestone Execution and Review Protocol.

## Standard Verification Commands

```bash
make format-check        # ruff format --check + ESLint/Prettier checks
make lint                # ruff + ESLint
make typecheck           # mypy + tsc --noEmit
make test-unit           # pytest unit + Vitest
make test-integration    # local Supabase/Redis/provider fakes
make test-security       # RLS, authz, secret-redaction, webhook-signature suites
make test-e2e            # Playwright + backend end-to-end scenarios
make eval                # versioned runner: v0 smoke from Task 9A, full suites from Task 45
make build               # backend/control-plane/worker container builds
make smoke               # Docker Compose readiness and one simulated turn
```

Each milestone ends with `make format-check lint typecheck test-unit test-integration`; security, E2E, eval, build, and smoke gates are added when their owned surfaces exist. Starting with Task 9A, every task that creates or modifies `evals/cases/*.jsonl` must execute those cases through the versioned runner before commit. After the milestone gates pass, produce the review package defined above and stop for explicit authorization of the next milestone.

---

## Phase 0 — Repository and Approved Baseline

### Task 0: Create the private GitHub monorepo and preserve the approved sources

**Files:**
- Create: `.gitignore`, `.editorconfig`, `README.md`
- Move: `Agents Factory — Master Product and Architecture Design Specification.txt` → `docs/superpowers/specs/2026-08-12-agents-factory-master-product-architecture.md`
- Preserve: `Agents Factory Client Onboarding Playbook.pdf`
- Modify: master specification approval metadata only
- Verify: `docs/superpowers/plans/2026-08-12-agents-factory-v1.md`

**Interfaces:**
- Produces: local Git repository on branch `main`; private GitHub repository `agents-factory`; remote named `origin`; canonical spec path used by all later tasks.

- [ ] **Step 1: Verify identity and protect sources before mutation**

  Run `gh auth status`, `git --version`, `gh --version`, and SHA-256 checksums for the two source files. Record the checksums in `docs/superpowers/specs/README.md`. Expected: GitHub CLI is authenticated to the user’s intended GitHub account and both files are readable.

- [ ] **Step 2: Write the repository acceptance check**

  Create `infrastructure/scripts/verify_repository.sh` that exits non-zero unless: branch is `main`; `origin` exists; `gh repo view --json visibility` reports `PRIVATE`; the canonical spec and PDF exist; and `git status --short` is empty. Run it before initialization and expect failure because the folder is not yet a Git repository.

- [ ] **Step 3: Create the minimal repository baseline**

  Initialize with `git init -b main`; move the spec to the canonical `.md` path; preserve the 2026-08-14 Generic REST amendment; change only stale approval metadata to “Approved v1 design — implementation authorized milestone by milestone”; record the original design approval and the dated scope amendment separately in Section 48 without implying authorization for later milestones; create `.gitignore` for secrets, local Supabase state, caches, media, builds, and eval results; create a README linking the spec, plan, and playbook.

- [ ] **Step 4: Commit locally and create the private remote**

  Run `git add .`, inspect `git diff --cached --stat` and `git diff --cached --check`, commit `docs: establish approved Agents Factory v1 baseline`, then run `gh repo create agents-factory --private --source=. --remote=origin --push`. Do not create a public repository or initialize a second local clone.

- [ ] **Step 5: Verify local and remote copies**

  Run `infrastructure/scripts/verify_repository.sh`, `git remote -v`, and `gh repo view --json nameWithOwner,visibility,defaultBranchRef,url`. Expected: `PRIVATE`, default branch `main`, clean local worktree, matching commit at local `HEAD` and `origin/main`.

**Acceptance criteria:** The approved sources and this plan exist in a private GitHub repository and in the current laptop folder; no product scaffold or dependency has been created.

---

## Phase 1 — Milestone 1: Platform Foundation

### Task 1: Bootstrap only the executable monorepo foundations

**Files:**
- Create: root `pyproject.toml`, `uv.lock`, `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `Makefile`, `.env.example`, `docker-compose.yml`
- Create: `apps/backend/pyproject.toml`, `apps/control-plane/package.json`
- Create: worker package manifests under `workers/*/pyproject.toml`
- Test: `infrastructure/scripts/smoke_compose.sh`

**Interfaces:**
- Produces: stable `make` commands; containers `control-plane`, `backend`, `agent-worker`, `knowledge-worker`, `outbound-worker`, `scheduler`, and `redis`; environment schema shared by all Python processes.

- [ ] **Step 1: Write the failing bootstrap smoke check**

  The script must assert that `uv sync --locked`, `pnpm install --frozen-lockfile`, `docker compose config --quiet`, and manifest checks pass. Run it and expect failure on missing manifests.

- [ ] **Step 2: Add pinned workspace manifests**

  First record current Supabase changelog/CLI and OpenAI Agents SDK documentation preflight results in the commit notes. Then configure Python `>=3.12,<3.14`, uv workspaces, Node `>=22`, pnpm workspaces, exact dependency locking, and scripts mapped to the Standard Verification Commands. Include only dependencies needed by Milestone 1; later milestones add their own packages.

- [ ] **Step 3: Add environment and Compose contracts**

  `.env.example` names every required variable without values or secrets. Compose adds readiness checks, dependency ordering, named Redis data, and separate commands for API/workers/scheduler; Supabase remains external/local-CLI managed rather than self-hosted inside this application Compose file.

- [ ] **Step 4: Run the smoke check**

  Expected: locked installs succeed, Compose configuration is valid, and no application container claims ready before its health endpoint exists.

- [ ] **Step 5: Commit**

  Commit `build: bootstrap locked monorepo workspaces` after `git diff --check`.

**Acceptance criteria:** One locked monorepo supports Python, TypeScript, and separate runtime processes without prematurely creating unused domain directories.

### Task 1A: Establish basic required CI before domain implementation accumulates

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `infrastructure/scripts/{verify_ci_workflow,check_repository_security}.sh`
- Modify: `Makefile`
- Test: `infrastructure/scripts/verify_ci_workflow.sh`

**Interfaces:**
- Consumes: Task 1 lockfiles and stable `make` commands.
- Produces: stable required GitHub check `ci-baseline`; PR and `main` validation for format, lint, typecheck, unit tests, Compose configuration, and basic repository/workflow/secret security; no deployment behavior.

- [ ] **Step 1: Write the failing workflow contract check**

  Assert the workflow runs for pull requests and pushes to `main`; pins every action by commit SHA; grants read-only contents permission by default; cancels superseded branch runs; installs only from `uv.lock` and `pnpm-lock.yaml`; exposes no provider credentials to pull requests; and contains one stable aggregate job named `ci-baseline`. Run the check and expect failure because the workflow does not exist.

- [ ] **Step 2: Implement the minimal CI workflow**

  Use pinned setup/cache actions, locked installs, and the root commands `make format-check`, `make lint`, `make typecheck`, `make test-unit`, and `docker compose config --quiet`. Keep external-provider and deployment credentials absent; recorded or fake provider tests are the only network-independent paths allowed in this baseline.

- [ ] **Step 3: Add the basic security gate**

  Make `make test-security` run repository secret/configuration checks immediately and automatically include the RLS/authz suites as their files are added. Reject committed environment files or credential-like fixtures, unpinned workflow actions, writable default workflow permissions, and accidental use of floating dependency installation.

- [ ] **Step 4: Verify CI and make it required**

  Run the workflow contract script and every baseline command locally, push the branch, inspect the first GitHub Actions run, and configure branch protection for `main` so `ci-baseline` is required. Expected: the same named check remains required as later tasks add tests behind the stable `make` targets.

- [ ] **Step 5: Commit**

  Commit `ci: enforce basic validation from milestone one` after the local baseline and workflow contract pass.

**Acceptance criteria:** Every subsequent pull request is blocked unless the locked workspace passes basic format, lint, type, unit, Compose, and repository-security validation; the workflow has minimal permissions and no deployment or external-provider secrets.

### Task 2: Establish the FastAPI kernel, typed configuration, and health contract

**Files:**
- Create: `apps/backend/src/agents_factory/{main,config,database,dependencies}.py`
- Create: `apps/backend/src/agents_factory/common/{context,ids,errors}.py`
- Test: `apps/backend/tests/unit/test_config.py`, `apps/backend/tests/contract/test_health.py`

**Interfaces:**
- Produces: `TenantContext`; RFC 9457-style API errors; `GET /health/live`; `GET /health/ready`; async transaction dependency.

- [ ] **Step 1: Write failing configuration and health tests**

  Assert startup fails with a list of missing environment variable names but never values; `/health/live` returns process liveness; `/health/ready` reports separate database and Redis states and returns 503 when either required dependency is unavailable.

- [ ] **Step 2: Run targeted tests**

  Run `uv run pytest apps/backend/tests/unit/test_config.py apps/backend/tests/contract/test_health.py -v`; expect import/route failures.

- [ ] **Step 3: Implement the minimal kernel**

  Use Pydantic settings with `SecretStr`; generate UUIDv7-compatible IDs through one factory; translate domain errors to stable `{type,title,status,detail,code,correlation_id}` responses; never log configuration values marked secret.

- [ ] **Step 4: Verify**

  Re-run targeted tests and `uv run mypy apps/backend/src`; expected pass.

- [ ] **Step 5: Commit**

  Commit `feat: add backend kernel and readiness contract`.

**Acceptance criteria:** All processes share one validated configuration model and readiness failures are observable without leaking secrets.

### Task 3: Create tenant, platform-admin, audit, and durable job schemas with RLS

**Files:**
- Create: `supabase/config.toml`
- Create: `supabase/migrations/*_foundation.sql` using `supabase migration new foundation`
- Create: `supabase/policies/tenant_isolation.sql`
- Create: `apps/backend/src/agents_factory/modules/tenants/{models,repository,service,router}.py`
- Create: `apps/backend/src/agents_factory/common/{audit,outbox}.py`
- Test: `supabase/tests/foundation_test.sql`, `apps/backend/tests/integration/test_tenants.py`, `apps/backend/tests/integration/test_outbox.py`

**Interfaces:**
- Produces: `tenants`, `platform_admins`, `audit_events`, `outbox_jobs`, `job_attempts`, `dead_letter_jobs`; `TenantRepository`; `AuditService.record()`; `OutboxService.enqueue()`.

- [ ] **Step 1: Create migration via the CLI and write failing pgTAP tests**

  Tests assert UUID primary keys, UTC timestamps, append-only audit events, unique outbox idempotency keys, no `BYPASSRLS` app/admin role, RLS enabled/forced on tenant-owned tables, and denied reads when tenant context is absent.

- [ ] **Step 2: Run the clean-database test**

  Run `supabase db reset` then `supabase test db`; expect failures before schema/policies exist.

- [ ] **Step 3: Implement schema, policies, and repositories**

  Use explicit grants; `USING` and `WITH CHECK` for writes; `security_invoker` views only; no authorization from `user_metadata`; transaction-local tenant context; append audit and outbox rows in the same transaction as business changes.

- [ ] **Step 4: Verify security and migration quality**

  Run pgTAP, backend integration tests, `supabase db lint`, and database advisors. Expected: zero policy/advisor errors and no cross-tenant row access.

- [ ] **Step 5: Commit**

  Commit `feat: add tenant-isolated data foundation`.

**Acceptance criteria:** Durable business/audit/job state is PostgreSQL-backed, tenant-owned tables fail closed, and privileged migration credentials are absent from runtime repositories.

### Task 4: Add Supabase Auth and the private `platform_admin` Control Plane shell

**Files:**
- Create: `apps/control-plane/middleware.ts`
- Create: `apps/control-plane/lib/{auth,api}.ts`
- Create: `apps/control-plane/app/{login,(authenticated)/layout}.tsx`
- Create: `apps/backend/src/agents_factory/common/security.py`
- Create: `apps/backend/src/agents_factory/modules/tenants/admin_router.py`
- Test: `apps/backend/tests/security/test_platform_admin_auth.py`, `apps/control-plane/tests/unit/auth.test.ts`, `apps/control-plane/tests/e2e/auth.spec.ts`

**Interfaces:**
- Consumes: `platform_admins`, backend error contract.
- Produces: verified admin principal; authenticated API client; canonical navigation shell with no product pages yet.

- [ ] **Step 1: Write failing auth tests**

  Cover missing/expired JWT, a valid user without `app_metadata.platform_role`, a valid `platform_admin`, server-side logout, and browser attempts to reach private routes directly.

- [ ] **Step 2: Run backend and frontend auth tests**

  Expect 401/403 contract or missing module failures.

- [ ] **Step 3: Implement least-privilege auth**

  Validate issuer, audience, signature, expiry, and `app_metadata`; never trust `user_metadata`; expose only the Supabase publishable key to the browser; keep all product data behind FastAPI.

- [ ] **Step 4: Verify**

  Run unit/security/Playwright auth suites. Expected: only `platform_admin` reaches authenticated pages and backend endpoints.

- [ ] **Step 5: Commit**

  Commit `feat: secure private platform admin shell`.

**Acceptance criteria:** v1 has exactly one Control Plane role and no client-facing portal surface.

### Task 5: Make tenant isolation a release-blocking test suite

**Files:**
- Create: `apps/backend/tests/security/test_tenant_isolation_matrix.py`
- Create: `supabase/tests/rls_matrix_test.sql`
- Create: `docs/security/tenant-isolation.md`
- Modify: `.github/workflows/ci.yml`, `Makefile`

**Interfaces:**
- Consumes: `TenantContext`, RLS roles/policies, repositories.
- Produces: reusable matrix fixture that every later tenant-owned table must register; RLS/authz coverage behind the required `ci-baseline` check.

- [ ] **Step 1: Write a red test using two tenants and two actors**

  For each registered table, assert select/insert/update/delete isolation, rejected tenant-ID reassignment, missing-context denial, and platform-admin access only through the separately authenticated admin path.

- [ ] **Step 2: Run and capture the initial failures**

  Execute `make test-security`; expect any unregistered or incorrectly protected foundation table to fail.

- [ ] **Step 3: Fix policies and create the registration helper**

  `assert_tenant_isolated(table_name, owner_column="tenant_id")` becomes mandatory for each subsequent migration’s security test.

- [ ] **Step 4: Verify**

  Run the matrix against a clean database and after seeded data, then verify the GitHub workflow invokes it through `make test-security`. Expected: no row, count, error detail, or timing branch exposes another tenant’s existence and the required `ci-baseline` check fails if the matrix is removed or red.

- [ ] **Step 5: Commit**

  Commit `test: enforce cross-tenant release blocker`.

**Acceptance criteria:** Every current tenant-owned table is registered in the reusable RLS attack matrix, missing/wrong tenant context fails closed for all CRUD paths, and the required CI check enforces the matrix automatically.

### Task 5A: Establish the tenant-isolated Secrets Foundation

**Files:**
- Create: `supabase/migrations/*_secrets_foundation.sql`
- Create: `apps/backend/src/agents_factory/modules/secrets/{contracts,envelope,repository,redaction}.py`
- Modify: `.env.example`, `Makefile`
- Test: `apps/backend/tests/security/{test_secret_envelope,test_secret_redaction,test_secret_tenant_isolation}.py`

**Interfaces:**
- Consumes: validated backend configuration, `TenantContext`, audit conventions, RLS policies, and the reusable isolation matrix.
- Produces: `secret_envelopes`; `KeyEncryptionProvider`; `EnvironmentMasterKeyProvider`; `SecretVault.store/load/delete`; opaque `SecretRef`; backend-only secret resolution with no integration- or provider-specific model.

- [ ] **Step 1: Write failing cryptographic and boundary tests**

  Require AES-256-GCM envelope encryption; a unique nonce for every write; authenticated tenant, secret-purpose, and record context; master key read only from the server environment; ciphertext-only database storage; key identifier/version metadata; denial on wrong tenant, purpose, context, or key; and RLS registration for the secret table. Assert plaintext is never a field on `SecretRef` or a serializable repository result.

- [ ] **Step 2: Run the clean-database security tests**

  Run the targeted secret tests, `supabase db reset`, `supabase test db`, and `make test-security`; expect missing schema/contracts and redaction failures before implementation.

- [ ] **Step 3: Implement the minimal provider-neutral vault**

  Keep envelope operations behind `KeyEncryptionProvider`; implement `EnvironmentMasterKeyProvider` without a database or frontend fallback; return `SecretRef` from storage; allow plaintext resolution only inside an authenticated backend call with matching `TenantContext` and purpose; audit store/load/delete metadata without values. Record key version and a re-encryption-compatible contract, but leave the operational rotation procedure and live rotation drill to Task 48.

- [ ] **Step 4: Verify isolation and non-disclosure paths**

  Exercise duplicate plaintext writes, wrong-tenant references, wrong-purpose loads, missing context, exceptions, logs, traces, JSON/Pydantic serialization, API error responses, database dumps, and test snapshots. Expected: unique ciphertext/nonce, fail-closed resolution, no plaintext/key leakage, and redacted audit evidence for every denied access.

- [ ] **Step 5: Commit**

  Commit `feat: establish tenant-isolated secrets foundation` after the targeted suite, RLS matrix, and required CI check pass.

**Acceptance criteria:** v1 has one provider-neutral, tenant-isolated, envelope-encrypted vault before any real provider authorization is stored; consumers receive opaque references, only backend services can resolve them for an authenticated purpose, and operational key rotation remains owned by Task 48.

**Milestone 1 acceptance:** A platform admin can authenticate and create/read tenants; all durable foundation and secret data is audited, tenant-isolated, encrypted, and redacted; the local stack passes format, lint, type, unit, integration, and security gates; the same baseline is green and required on GitHub before merge.

---

## Phase 2 — Milestone 2: Messaging Runtime

### Task 6: Implement the Meta provider boundary, signature verification, tenant resolution, and inbound deduplication

**Files:**
- Create: `apps/backend/src/agents_factory/modules/whatsapp/{contracts,meta_provider,schemas,webhook,repository}.py`
- Create: `supabase/migrations/*_whatsapp_inbound.sql`
- Test: `apps/backend/tests/contract/test_meta_webhook.py`, `apps/backend/tests/integration/test_whatsapp_deduplication.py`, `apps/backend/tests/security/test_webhook_signature.py`

**Interfaces:**
- Produces: `WhatsAppProvider`; `InboundWhatsAppEvent`; tables `whatsapp_accounts`, `whatsapp_webhook_events`; dedupe key `(tenant_id, whatsapp_message_id)`; `POST /webhooks/meta/whatsapp`.

- [ ] **Step 1: Write failing provider/webhook tests**

  Use captured, redacted Meta fixture payloads for verification challenge, valid/invalid HMAC signature, unknown WABA/phone mapping, supported message types, delivery status callbacks, and duplicate delivery.

- [ ] **Step 2: Run targeted tests**

  Expected: route/provider imports fail and no events persist.

- [ ] **Step 3: Implement verify-resolve-persist-ack**

  Read raw bytes before JSON parsing; verify signature with constant-time comparison; resolve tenant only from an active account/number mapping; normalize event metadata; insert with a unique dedupe constraint; commit before enqueue intent; return a quick 2xx for valid accepted or already-seen events.

- [ ] **Step 4: Verify isolation and replay behavior**

  Run the signature, contract, dedupe, and RLS suites. Expected: invalid signatures persist nothing; unknown mappings fail closed; 100 replays create one event and one outbox intent.

- [ ] **Step 5: Commit**

  Commit `feat: persist signed WhatsApp events idempotently`.

**Acceptance criteria:** Meta-specific parsing stops at the provider boundary, inbound data is durable before queueing, and duplicate webhooks cannot multiply work.

### Task 7: Add ARQ queues, PostgreSQL outbox reconciliation, ordering locks, and DLQ

**Files:**
- Create: `apps/backend/src/agents_factory/common/{queue,locks}.py`
- Create: `workers/agent-worker/src/agent_worker/worker.py`
- Create: `workers/knowledge-worker/src/knowledge_worker/worker.py`
- Create: `workers/outbound-worker/src/outbound_worker/worker.py`
- Create: `workers/scheduler/src/scheduler/worker.py`
- Test: `apps/backend/tests/integration/test_outbox_dispatch.py`, `apps/backend/tests/integration/test_conversation_lock.py`, `apps/backend/tests/integration/test_dead_letter.py`

**Interfaces:**
- Consumes: `outbox_jobs`, `job_attempts`, `dead_letter_jobs`.
- Produces: `JobEnvelope(job_id, tenant_id, kind, aggregate_id)`; ARQ queues `agent`, `knowledge`, `outbound`, `scheduler`; lock key `tenant_id:conversation_id`.

- [ ] **Step 1: Write failing reliability tests**

  Cover database commit before enqueue, dispatcher crash after enqueue but before marking dispatched, duplicate `_job_id`, worker cancellation and redelivery, two messages in one conversation, parallel messages in different conversations, bounded attempts, and terminal DLQ creation.

- [ ] **Step 2: Run with local PostgreSQL and Redis**

  Expect missing dispatchers/workers and ordering failures.

- [ ] **Step 3: Implement the durable ledger pattern**

  Reconciler claims outbox rows with `FOR UPDATE SKIP LOCKED`; ARQ receives the durable UUID as `_job_id` in a JSON-serialized `JobEnvelope`; worker loads the row under `TenantContext`, records each attempt, renews a bounded Redis lock, and atomically marks completion or retry. Exhausted attempts create one inspectable DLQ row and audit event.

- [ ] **Step 4: Verify under crash simulation**

  Kill a worker between side-effect preparation and completion, restart it, and assert at-least-once delivery with idempotent business outcome. Verify conversation serialization and tenant concurrency.

- [ ] **Step 5: Commit**

  Commit `feat: add durable async job coordination`.

**Acceptance criteria:** Redis loss may delay work but cannot erase durable intent or invent success; repeated failures become auditable DLQ items.

### Task 8: Persist conversations/messages and enforce conversation control state

**Files:**
- Create: `supabase/migrations/*_conversations.sql`
- Create: `apps/backend/src/agents_factory/modules/conversations/{models,repository,service,state_machine}.py`
- Test: `apps/backend/tests/unit/conversations/test_control_state.py`, `apps/backend/tests/integration/test_conversation_ingest.py`, `apps/backend/tests/security/test_human_active_silence.py`

**Interfaces:**
- Produces: `conversations`, `messages`, `conversation_state_events`; `ConversationService.ingest(event_id)`; exact `ConversationControlState` transitions.

- [ ] **Step 1: Write failing state and persistence tests**

  Assert `AI_ACTIVE` may respond, `AWAITING_HUMAN` follows configured waiting policy, `HUMAN_ACTIVE` persists inbound messages but produces no response job, `CLOSED` opens a new AI-active session only according to policy, and workflow case states never mutate conversation control implicitly.

- [ ] **Step 2: Run targeted unit/integration/security tests**

  Expected: missing schema/state service.

- [ ] **Step 3: Implement explicit transition commands**

  Use `request_handoff`, `activate_human`, `close_conversation`, and `reopen_for_inbound`; reject direct state writes; record actor/reason/version for every transition; keep message ordering by provider timestamp plus persisted arrival sequence.

- [ ] **Step 4: Verify the hard silence invariant**

  Inject inbound text, status callbacks, duplicate events, and delayed jobs while `HUMAN_ACTIVE`. Expected: messages/audit remain complete and outbound attempt count is zero.

- [ ] **Step 5: Commit**

  Commit `feat: separate conversation control from workflow state`.

**Acceptance criteria:** Conversation authority is explicit, auditable, and independent of cases/actions.

### Task 9: Define the runtime adapter, Customer Service turn contract, and dynamic tool gating

**Files:**
- Create: `apps/backend/src/agents_factory/modules/runtime/{contracts,openai_adapter,tool_registry,turn_service}.py`
- Create: `apps/backend/src/agents_factory/modules/runtime/prompts/customer_service_core.md`
- Create: `workers/agent-worker/src/agent_worker/jobs.py`
- Test: `apps/backend/tests/unit/runtime/test_tool_gating.py`, `apps/backend/tests/contract/runtime/test_openai_adapter.py`, `apps/backend/tests/integration/runtime/test_agent_turn.py`

**Interfaces:**
- Consumes: `AgentRuntime`, conversation/message repositories.
- Produces: `AgentTurnInput`, `RuntimeTool`, `AgentTurnResult`; `OpenAIAgentsRuntime`; `AgentTurnService.process(conversation_id, inbound_message_id)`.

- [ ] **Step 1: Write failing runtime contract tests**

  Assert the adapter receives one immutable AgentSpec, only relevant active capability tools, no credentials/raw refresh tokens, bounded runtime limits, trace metadata, and model configuration `gpt-5.6-luna`/`low`.

- [ ] **Step 2: Write a fake-runtime integration test**

  A persisted inbound message becomes one `AgentTurnInput`; a structured assistant result persists before an outbound job; `HUMAN_ACTIVE` and inactive AgentSpec versions short-circuit before runtime invocation.

- [ ] **Step 3: Implement the single-runtime boundary**

  Start with one Agents SDK `Agent`; expose deterministic function tools generated from `RuntimeTool`; keep sessions/product state in Agents Factory repositories; map SDK usage/traces/errors into internal result types; enforce max tokens/tool calls/timeout from AgentSpec.

- [ ] **Step 4: Verify fake and recorded-provider paths**

  Run without a network key using the fake adapter, then run an opt-in recorded contract smoke with `OPENAI_API_KEY` outside CI secrets logs. Expected: stable internal output regardless of provider trace IDs.

- [ ] **Step 5: Commit**

  Commit `feat: isolate OpenAI agent runtime behind contract`.

**Acceptance criteria:** The model interprets and selects gated tools, while product state and controls remain server-owned; no second runtime or specialist-agent orchestration exists.

### Task 9A: Create Eval Runner v0 on the deterministic runtime path

**Files:**
- Create: `evals/{README.md,run_local.py,graders.py,case_schema.py}`
- Create: `evals/cases/runtime_smoke.jsonl`, `evals/results/.gitignore`
- Modify: `Makefile`, `.github/workflows/ci.yml`
- Test: `apps/backend/tests/unit/evals/test_runner_v0.py`

**Interfaces:**
- Consumes: Task 9 runtime/turn contracts and fake runtime; Task 1A stable CI check.
- Produces: versioned `EvalCase` schema; `EvalGrader` protocol; deterministic local runner with explicit seed, normalized JSON result artifact, and non-zero exit on case or grader failure; `make eval` smoke gate.

- [ ] **Step 1: Write failing runner and schema tests**

  Require a declared case-schema version, stable case ID, input turn, fixture setup, expected structured outcomes, grader list, and optional tags. Assert unknown fields/graders and duplicate IDs fail validation; runner order and seeded fake-runtime results are reproducible; a failed expectation exits non-zero.

- [ ] **Step 2: Add the first executable runtime smoke case**

  Encode a deterministic Spanish/English-safe Customer Service turn using the fake runtime, with structured checks for response existence, selected tools, persisted result, and absence of credentials. Run it before the runner exists and expect the targeted test/CLI to fail.

- [ ] **Step 3: Implement the minimal local harness**

  Load validated JSONL cases, reset in-memory fixture state per case, invoke the fake runtime/turn contract, run structured graders, redact artifacts, and write a timestamp-independent normalized JSON summary plus optional diagnostic details under ignored `evals/results/`. Do not add database persistence, API routes, Control Plane UI, real-provider execution, aggregate release thresholds, or Production publication decisions in v0.

- [ ] **Step 4: Wire and verify the early eval gate**

  Make `make eval` execute the v0 smoke suite and add it to `ci-baseline`. Run twice with the same seed and compare normalized results; then introduce one deliberate failing expectation and verify a non-zero exit before restoring it. Expected: every later `evals/cases/*.jsonl` file can run immediately through the same contract.

- [ ] **Step 5: Commit**

  Commit `test: add deterministic eval runner v0` after unit, smoke, redaction, reproducibility, and CI checks pass.

**Acceptance criteria:** The first runtime path has a deterministic, versioned, CI-enforced eval runner before capability suites accumulate; v0 reports case failures reliably but does not claim to be the Production Quality Gate.

### Task 10: Implement outbound text delivery, Meta template registry, delivery status, and message idempotency

**Files:**
- Create: `supabase/migrations/*_whatsapp_outbound_templates.sql`
- Create: `apps/backend/src/agents_factory/modules/whatsapp/{outbound_service,template_service}.py`
- Create: `workers/outbound-worker/src/outbound_worker/jobs.py`
- Test: `apps/backend/tests/contract/test_meta_outbound.py`, `apps/backend/tests/integration/test_outbound_idempotency.py`, `apps/backend/tests/integration/test_template_policy.py`

**Interfaces:**
- Produces: `outbound_messages`, `whatsapp_templates`; `OutboundTextRequest`; `OutboundTemplateRequest`; `OutboundMessageService.send(message_id)`.

- [ ] **Step 1: Write failing delivery tests**

  Cover free-form in-window text, proactive initiation requiring an approved template, ownership/language/variable validation, retry after timeout, duplicate job, provider rejection, delivery/read/failure callbacks, and cost attribution metadata.

- [ ] **Step 2: Run tests against the Meta fake**

  Expect missing registry/service.

- [ ] **Step 3: Implement prepare-persist-send-reconcile**

  Persist an outbound intent with an idempotency key before provider call; validate current conversation authority again; render only registered variables; store provider ID/result; reconcile status callbacks; classify unknown send outcomes as uncertain for later verification rather than retrying blindly.

- [ ] **Step 4: Verify**

  Replay outbound jobs and callbacks. Expected: one customer-visible message, complete status history, tenant/cost attribution, and no unapproved proactive message.

- [ ] **Step 5: Commit**

  Commit `feat: deliver idempotent WhatsApp text and templates`.

**Acceptance criteria:** v1 sends text only, syncs/maps approved Meta templates, and observes delivery without implementing a template editor.

### Task 11: Add Meta Embedded Signup, account mapping, connection health, and API-only/Coexistence metadata

**Files:**
- Create: `apps/backend/src/agents_factory/modules/whatsapp/{signup_service,account_service,router}.py`
- Create: `apps/control-plane/app/(authenticated)/tenants/[tenantId]/whatsapp/page.tsx`
- Test: `apps/backend/tests/contract/test_meta_embedded_signup.py`, `apps/control-plane/tests/e2e/whatsapp-setup.spec.ts`

**Interfaces:**
- Consumes: `SecretVault`, `SecretRef` from Task 5A.
- Produces: account onboarding endpoints; `WhatsAppMode = API_ONLY | COEXISTENCE`; health/scope summary; verified tenant/number mapping whose provider credentials are opaque secret references.

- [ ] **Step 1: Write failing signup/account tests**

  Cover client-owned authorization callback, state/tenant binding, revoked token, duplicate phone mapping, wrong WABA ownership, missing scopes, API-only default, and explicit Coexistence eligibility result.

- [ ] **Step 2: Run contract and UI tests**

  Expect missing endpoints/page.

- [ ] **Step 3: Implement authorization completion and health checks**

  Never request credentials through a form; store received tokens immediately through `SecretVault` and persist only `SecretRef`; resolve tokens only inside the backend Meta provider call with matching tenant/purpose context. Surface permissions, mapping, last health check, and reconnect/revoke actions without returning credential values.

- [ ] **Step 4: Verify with Meta sandbox/test account**

  Expected: one tenant owns the mapped number, webhook verification succeeds, mode is explicit, and handoff capability is not inferred merely from Cloud API connection.

- [ ] **Step 5: Commit**

  Commit `feat: onboard tenant-owned WhatsApp accounts`.

**Acceptance criteria:** A client-owned Meta test account completes the authorization/mapping flow using the production Secrets Foundation from its first implementation, reports explicit API-only or eligible Coexistence mode, exposes no token value, and never implies a live-human surface from API connectivity alone.

**Milestone 2 acceptance:** A valid signed WhatsApp event is tenant-resolved, deduplicated, persisted, serialized, processed by the runtime boundary, and returned as one observable text message; Meta authorization uses backend-only `SecretRef`; `HUMAN_ACTIVE` blocks the runtime/outbound path; Redis/worker failures are recoverable and inspectable; Eval Runner v0 passes its deterministic runtime smoke in local and required CI execution.

---

## Phase 2 — Milestone 3: AgentSpec, Customer Service Core, Identity, and Actions

### Task 12: Define AgentSpec and immutable configuration versioning

**Files:**
- Create: `apps/backend/src/agents_factory/modules/agent_factory/{schemas,models,repository,compiler,service,router}.py`
- Create: `packages/agent-spec/agent_spec.schema.json`, `packages/agent-spec/README.md`
- Create: `supabase/migrations/*_agent_spec_versions.sql`
- Test: `apps/backend/tests/unit/agent_factory/test_compiler.py`, `apps/backend/tests/integration/agent_factory/test_version_lifecycle.py`, `apps/backend/tests/contract/test_agent_spec_schema.py`

**Interfaces:**
- Produces: immutable `AgentSpec`; `AgentSpecCompiler.compile(agent_instance_id, draft_version_id)`; `promote_to_test`, `enter_quality_gate`, `publish_production`, `rollback_to`; fail-closed `ProductionQualityGate` port later implemented by Task 45.

- [ ] **Step 1: Write failing schema/compiler tests**

  Require tenant, product/version, persona, capability versions, permitted tools, connector bindings, policy/identity/approval/knowledge versions, model/reasoning, language, human operations, and runtime limits. Assert deterministic canonical JSON and digest for equal inputs.

- [ ] **Step 2: Write failing lifecycle tests**

  Assert every configuration change creates a new Draft, only valid transitions occur, Production rows are immutable at database and service layers, rollback selects a prior compatible version, software environment state never changes AgentSpec state, and `publish_production` fails closed when no exact-digest Production Quality Gate implementation/evidence is available.

- [ ] **Step 3: Implement models/compiler/lifecycle**

  Store component version references and compiled JSON plus SHA-256 digest; use an append-only deployment record; route publication through `ProductionQualityGate`; reject publish without a successful decision tied to the exact AgentSpec, Knowledge, and code digests. Eval Runner v0 never satisfies this port, so Production remains disabled until Task 45 implements it.

- [ ] **Step 4: Verify generated schema and immutability**

  Generate `agent_spec.schema.json` from Pydantic, validate fixtures, attempt direct Production updates, and run isolation matrix.

- [ ] **Step 5: Commit**

  Commit `feat: add immutable AgentSpec lifecycle`.

**Acceptance criteria:** Every runtime turn can identify the exact executable configuration, Production cannot change silently, and the lifecycle is usable through Test while Production fails closed until the full exact-digest gate exists.

### Task 13: Build versioned Capability/Connector registries and the Tenant Extension boundary

**Files:**
- Create: `apps/backend/src/agents_factory/modules/capabilities/{contracts,registry,service,router}.py`
- Create: `apps/backend/src/agents_factory/modules/integrations/{contracts,registry}.py`
- Create: `packages/integrations/connector.schema.json`, `packages/integrations/README.md`
- Create: `docs/architecture/tenant-extensions.md`
- Test: `apps/backend/tests/unit/capabilities/test_registry.py`, `apps/backend/tests/unit/integrations/test_operation_gating.py`, `apps/backend/tests/architecture/test_no_tenant_conditionals.py`

**Interfaces:**
- Produces: `CapabilityManifest`, `ActionDefinition`, `ConnectorManifest`, `ConnectorRequest`, `ConnectorResult`, `TenantExtensionManifest`; registries keyed by stable name + version.

- [ ] **Step 1: Write failing manifest/gating tests**

  Assert a tool appears only if the AgentSpec activates its capability and the bound connector declares that operation; unsupported operations are not offered; capability versions contain intents, workflow, schemas, risk/identity/confirmation/approval/failure/handoff/eval metadata.

- [ ] **Step 2: Write architecture enforcement test**

  Scan core Python/TypeScript source for literal tenant UUIDs and forbidden `if tenant_id ==` patterns; require extension manifests to declare owner, semantic version, compatibility range, isolated tests, enable/disable state, deployment artifact, and rollback target; load only by registered entry point, with disabled by default and no extensions shipped in v1.

- [ ] **Step 3: Implement the registries and schemas**

  Separate business operation names such as `orders.get_status` from provider methods; validate manifests at startup and AgentSpec compile time; expose Generic REST, Microsoft 365/OneDrive/SharePoint, HubSpot, Shopify, CRM/helpdesk, accounting, Salesforce, and other planned connector metadata as unavailable only, with no auth route, webhook, client, or executable adapter.

- [ ] **Step 4: Verify**

  Run manifest JSON-schema tests, tool gating matrix, and architecture scan.

- [ ] **Step 5: Commit**

  Commit `feat: separate capabilities connectors and extensions`.

**Acceptance criteria:** Standard onboarding is configuration-only, unsupported provider operations cannot reach the model, and v1 contains no customer-exclusive behavior.

### Task 14: Implement identity assurance independently from authorization

**Files:**
- Create: `apps/backend/src/agents_factory/modules/identity/{models,repository,methods,service,router}.py`
- Create: `supabase/migrations/*_identity.sql`
- Test: `apps/backend/tests/unit/identity/test_assurance_levels.py`, `apps/backend/tests/integration/identity/test_challenges.py`, `apps/backend/tests/security/test_identity_is_not_authorization.py`

**Interfaces:**
- Produces: `IdentityLevel`; `IdentityEvidence`; `IdentityService.assess(customer_ref)`; `IdentityService.challenge(required_level)`; `AuthorizationDecision` remains a separate policy input.

- [ ] **Step 1: Write failing assurance tests**

  Cover unknown customer, recognized WhatsApp number, tenant-configured additional verification, OTP/external strong verification, expiry, retry limits, evidence reuse rules, and a recognized number lacking permission for a specific resource.

- [ ] **Step 2: Run tests**

  Expect missing identity schema/service.

- [ ] **Step 3: Implement methods and evidence ledger**

  Store challenge method/result/expiry and redacted evidence; never log OTP values; calculate achieved level from valid evidence; require authorization checks against tenant/resource/action even after identity passes.

- [ ] **Step 4: Verify abuse and isolation cases**

  Replay expired/foreign-tenant challenges and guessed OTPs. Expected: bounded failures, audited denial, no information about another customer/resource.

- [ ] **Step 5: Commit**

  Commit `feat: add layered identity assurance`.

**Acceptance criteria:** Levels 0–3 are enforced as evidence thresholds and never imply broad authorization.

### Task 15: Implement deterministic action policy, confirmation, lifecycle, idempotency, revalidation, and uncertainty

**Files:**
- Create: `apps/backend/src/agents_factory/modules/policies/{models,evaluator,service}.py`
- Create: `apps/backend/src/agents_factory/modules/actions/{models,repository,state_machine,service,router}.py`
- Create: `supabase/migrations/*_actions_policies.sql`
- Test: `apps/backend/tests/unit/policies/test_risk_matrix.py`, `apps/backend/tests/unit/actions/test_state_machine.py`, `apps/backend/tests/integration/actions/test_idempotency.py`, `apps/backend/tests/security/test_consequential_action_guards.py`

**Interfaces:**
- Produces: `ActionRequirement(identity_level, confirmation_required, approval_required)`; `ActionService.request`, `confirm`, `approve_reference`, `execute`; immutable action event ledger.

- [ ] **Step 1: Write failing risk/transition tests**

  Assert minimum defaults LOW=execute after identity/authorization, MEDIUM=customer confirmation, HIGH=confirmation+approval; stricter tenant policy is allowed and weaker policy rejected. Test legal skips for LOW reads and every terminal outcome.

- [ ] **Step 2: Write failing consequential-action tests**

  Cover normalized parameters, confirmation bound to exact parameter digest, duplicate `action_id`, expired confirmation, absent approval route, precondition change, safe retry for reads, unknown write result, and false-success copy prohibition.

- [ ] **Step 3: Implement deterministic orchestration**

  The model can propose an `ActionRequest` but only `ActionService` advances state. Persist action/audit/outbox in one transaction; every action records action ID, tenant, conversation, customer reference, capability/action type, risk, achieved identity, normalized parameters, confirmation evidence, optional approval reference, connector, result, and timestamps; call connector with `action_id` idempotency key; re-read external/current state before execute; map ambiguous timeout to `UNCERTAIN` plus verification/backoffice path.

- [ ] **Step 4: Verify release blockers**

  Run security tests proving no sensitive write without identity/authorization, no required-confirmation bypass, no HIGH execution without approval, and no success message for `UNCERTAIN`.

- [ ] **Step 5: Commit**

  Commit `feat: enforce auditable consequential actions`.

**Acceptance criteria:** Every action records the required audit fields and deterministic state; retry cannot duplicate an operation or customer claim.

### Task 16: Encode the Customer Service Core policies, persona, language, scope, transparency, and abuse behavior

**Files:**
- Create: `apps/backend/src/agents_factory/modules/runtime/customer_service/{instructions,language,scope,quick_options,policy}.py`
- Modify: `apps/backend/src/agents_factory/modules/runtime/prompts/customer_service_core.md`
- Test: `evals/cases/core_conversation.jsonl`, `apps/backend/tests/unit/runtime/test_quick_options.py`, `apps/backend/tests/unit/runtime/test_transparency_policy.py`

**Interfaces:**
- Consumes: AgentSpec persona/language/capabilities/handoff settings.
- Produces: deterministic instruction sections and quick options; policy classifier outputs `IN_SCOPE | REDIRECT | SAFETY_INCIDENT`.

- [ ] **Step 1: Add failing deterministic tests and eval cases**

  Cover named/brand greeting, free natural input, truthful automation disclosure when asked, no impersonation, Spanish/English response, isolated foreign term, operational intent hidden in weather/context, prompt injection, valid request with rude language, pure repeated abuse, credible threat evidence routing, and ambiguous “necesito ayuda”.

- [ ] **Step 2: Run unit tests and Eval Runner v0 against the fake runtime**

  Expect missing builders/policies and failed behavior graders.

- [ ] **Step 3: Implement composable core instructions and deterministic gates**

  Generate quick options only from active capabilities; show “Hablar con una persona” only with enabled/valid handoff surface; redirect non-business requests naturally; preserve safety/isolation/authorization rules outside tenant-customizable persona fields.

- [ ] **Step 4: Verify**

  Run `core_conversation.jsonl` through Eval Runner v0 in both languages with paraphrase variants. Expected: required policies pass without exact-prose grading except truthful disclosure semantics.

- [ ] **Step 5: Commit**

  Commit `feat: encode reusable customer service core`.

**Acceptance criteria:** The reusable core passes bilingual scope/transparency/abuse/injection evals, generates capability-driven orientation options, and keeps all safety invariants outside tenant-customizable persona fields.

**Milestone 3 acceptance:** A Draft AgentSpec compiles deterministically, tool exposure is capability/connector gated, Production versions are immutable, identity and authorization remain separate, and consequential actions cannot bypass deterministic confirmation/approval/uncertainty rules.

---

## Phase 3 — Milestone 4: Knowledge

### Task 17: Model structured business data, knowledge sources, authority, provenance, and versions

**Files:**
- Create: `supabase/migrations/*_knowledge_foundation.sql`
- Create: `apps/backend/src/agents_factory/modules/knowledge/{models,schemas,repository,service,router}.py`
- Test: `supabase/tests/knowledge_rls_test.sql`, `apps/backend/tests/integration/knowledge/test_sources.py`, `apps/backend/tests/unit/knowledge/test_authority.py`

**Interfaces:**
- Produces: `KnowledgeAuthority = AUTHORITATIVE | SECONDARY | REFERENCE`; tables `knowledge_sources`, `knowledge_source_versions`, `structured_facts`, `knowledge_documents`, `knowledge_versions`, `knowledge_version_members`; `KnowledgeRepository`.

- [ ] **Step 1: Write failing schema and authority tests**

  Require source type, authority, source version, verification timestamp, approving admin, tenant ownership, content digest, and lifecycle state. Assert business hours/locations/services/prices/contacts/booking/approval contacts are structured facts, not vector-only records.

- [ ] **Step 2: Run clean-database and repository tests**

  Expect missing schema and RLS registration.

- [ ] **Step 3: Implement source/version repositories**

  Enforce append-only source versions; allow lower-authority sources to coexist but never silently supersede a conflicting higher-authority fact; bind each AgentSpec to one immutable Knowledge version.

- [ ] **Step 4: Verify**

  Run authority permutations, isolation matrix, and provenance serialization. Expected: every returned critical fact points to its source/version/approval.

- [ ] **Step 5: Commit**

  Commit `feat: add authoritative versioned knowledge model`.

**Acceptance criteria:** Structured operational facts and unstructured knowledge have separate storage/query paths and full provenance.

### Task 18: Add tenant-scoped source ingestion and normalized extraction

**Files:**
- Create: `apps/backend/src/agents_factory/modules/knowledge/ingestion/{contracts,website,pdf,docx,spreadsheet,manual,drive,normalizer}.py`
- Create: `workers/knowledge-worker/src/knowledge_worker/jobs.py`
- Test: `apps/backend/tests/unit/knowledge/ingestion/`, `apps/backend/tests/integration/knowledge/test_ingestion_jobs.py`
- Fixtures: `apps/backend/tests/fixtures/knowledge/site/index.html`, `apps/backend/tests/fixtures/knowledge/policy.pdf`, `apps/backend/tests/fixtures/knowledge/manual.docx`, `apps/backend/tests/fixtures/knowledge/catalog.xlsx`, `apps/backend/tests/fixtures/knowledge/google_sheet_rows.json`

**Interfaces:**
- Produces: `SourceFetcher.fetch(source) -> FetchedSource`; `DocumentExtractor.extract(fetched) -> ExtractedDocument`; `ProposedFact`; `ProposedDocument`.

- [ ] **Step 1: Create sanitized extraction fixtures and failing tests**

  Test website allowlisted crawling, PDF text extraction, DOCX headings/tables, XLSX/Google Sheets rows, Google Drive file metadata, manual entry, unsupported/encrypted file rejection, size/type limits, source digesting, and tenant-scoped storage paths.

- [ ] **Step 2: Run extraction tests without external network**

  Expect missing fetchers/extractors.

- [ ] **Step 3: Implement fetch/extract/normalize jobs**

  Fetch only configured sources; prevent private-network/metadata SSRF; store original content privately; normalize text/tables with page/sheet/URL locators; create Draft proposals only; redact secrets from parser errors.

- [ ] **Step 4: Verify job replay and malformed inputs**

  Re-run the same source digest and assert one version/proposal set; malformed files create an audited failed ingestion without changing Production knowledge.

- [ ] **Step 5: Commit**

  Commit `feat: ingest approved knowledge sources safely`.

**Acceptance criteria:** Website, PDF, DOCX, Drive, spreadsheet, and manual sources produce reviewable Draft artifacts and never auto-publish.

### Task 19: Implement pgvector chunking, embeddings, tenant-scoped retrieval, and provenance

**Files:**
- Create: `supabase/migrations/*_knowledge_vectors.sql`
- Create: `apps/backend/src/agents_factory/modules/knowledge/{chunking,embeddings,retrieval}.py`
- Create: `workers/knowledge-worker/src/knowledge_worker/embedding_jobs.py`
- Test: `apps/backend/tests/unit/knowledge/test_chunking.py`, `apps/backend/tests/integration/knowledge/test_retrieval.py`, `apps/backend/tests/security/test_vector_tenant_isolation.py`

**Interfaces:**
- Produces: `knowledge_chunks`; `EmbeddingProvider`; `KnowledgeQuery`; `KnowledgeHit(text, score, source_id, source_version_id, authority, locator)`.

- [ ] **Step 1: Write failing deterministic chunk/retrieval tests**

  Assert stable chunks/digests, semantic metadata, no cross-document overlap, language-aware retrieval, authority-aware ranking, Knowledge-version filter, top-k/runtime limits, and no results without tenant context.

- [ ] **Step 2: Run with deterministic fake embeddings**

  Expect missing vector schema/retriever.

- [ ] **Step 3: Implement pgvector repository behind `KnowledgeRepository`**

  Use parameterized tenant/version filters in the database query, appropriate vector index for measured corpus size, explicit authority boost/tie rules, and citations/provenance in every hit. Keep embedding model/version metadata so re-embedding creates a new Draft artifact.

- [ ] **Step 4: Verify isolation and relevance**

  Seed identical text in two tenants and assert each query returns only its tenant/source; run a fixed bilingual relevance set and record latency/recall baseline.

- [ ] **Step 5: Commit**

  Commit `feat: add tenant-scoped knowledge retrieval`.

**Acceptance criteria:** RAG cannot cross tenants or inactive Knowledge versions and always returns source authority/provenance.

### Task 20: Add AI-assisted proposals, conflict review, source-change detection, and Knowledge publication

**Files:**
- Create: `supabase/migrations/*_knowledge_review.sql`
- Create: `apps/backend/src/agents_factory/modules/knowledge/{proposals,conflicts,change_detection,publishing}.py`
- Create: `workers/scheduler/src/scheduler/knowledge_jobs.py`
- Test: `apps/backend/tests/unit/knowledge/test_conflicts.py`, `apps/backend/tests/integration/knowledge/test_publish_flow.py`, `apps/backend/tests/integration/knowledge/test_change_detection.py`

**Interfaces:**
- Produces: `knowledge_proposals`, `knowledge_conflicts`, `SourceDiff`; actions `approve`, `edit`, `reject`; version lifecycle contract bound to the Knowledge digest, usable through Test while Production remains fail-closed until Task 45.

- [ ] **Step 1: Write failing review/conflict tests**

  Cover higher/lower/equal authority conflicts, unchanged source digest, changed source diff, critical unresolved conflict, admin edit provenance, rejected proposal, simultaneous review, and attempted direct Production mutation.

- [ ] **Step 2: Run targeted tests**

  Expect missing review schema/services.

- [ ] **Step 3: Implement proposal and publish transactions**

  AI output is schema-validated and marked proposed; first valid admin decision closes each proposal revision; source changes create a new Draft/diff; a Test candidate requires no unresolved critical conflict and successful Eval Runner v0 knowledge cases tied to its exact digest. Route Production publication through the fail-closed `ProductionQualityGate`; only Task 45 may supply a passing implementation.

- [ ] **Step 4: Verify silent-change prevention**

  Using an immutable active-version fixture, change a connected source and run the scheduler. Expected: active answers remain unchanged, a Draft diff appears, audit identifies source/version/admin decisions, and a real Production publish attempt is rejected because the full Quality Gate is not yet available.

- [ ] **Step 5: Commit**

  Commit `feat: review and version knowledge candidates`.

**Acceptance criteria:** Connected source changes are detectable and reviewable but cannot alter an active version; Knowledge reaches reviewed Test with executable v0 evidence, while Production publication remains visibly and technically blocked until Task 45.

### Task 21: Expose structured data and RAG as separate runtime tools

**Files:**
- Create: `apps/backend/src/agents_factory/modules/knowledge/tools.py`
- Modify: `apps/backend/src/agents_factory/modules/runtime/tool_registry.py`
- Test: `apps/backend/tests/unit/knowledge/test_runtime_tools.py`, `evals/cases/knowledge_authority.jsonl`

**Interfaces:**
- Produces: tools `business_data.lookup` and `knowledge.search`; both consume AgentSpec Knowledge version and `TenantContext`.

- [ ] **Step 1: Write failing tool-selection tests**

  Assert hours/prices/booking rules use structured lookup, policy/manual questions use RAG, missing critical facts produce a safe unknown/escalation result, and lower-authority text cannot override an authoritative structured value.

- [ ] **Step 2: Run tool tests and `knowledge_authority.jsonl` through Eval Runner v0**

  Expect missing tools/incorrect selection.

- [ ] **Step 3: Implement narrow schemas and normalized results**

  Return structured values or sourced snippets, not raw database rows; cap content; include source/version/authority/locator; omit tools when no Production Knowledge binding exists.

- [ ] **Step 4: Verify bilingual and injection cases**

  Run Spanish/English `knowledge_authority.jsonl` cases through Eval Runner v0, including malicious source text. Expected: source content cannot change system/action policy and answers cite the active tenant source.

- [ ] **Step 5: Commit**

  Commit `feat: expose approved knowledge to agent runtime`.

**Acceptance criteria:** Runtime knowledge tools return only the active tenant/version, separate structured facts from RAG, preserve authority/provenance, and safely decline when critical approved knowledge is unavailable.

**Milestone 4 acceptance:** A platform admin can ingest supported sources, review AI proposals/conflicts, prepare an immutable Test Knowledge version, and receive tenant-scoped structured/RAG answers with authority and provenance in Test; connected changes produce Drafts only; Production publication is fail-closed and explicitly deferred to the complete Quality Gate in Task 45.

---

## Phase 3 — Milestone 5: Initial Connectors and Capability Packs

### Task 22: Implement connector connections, OAuth lifecycle, health, and the Integration Catalog on the Secrets Foundation

**Files:**
- Create: `supabase/migrations/*_integration_connections.sql`
- Create: `apps/backend/src/agents_factory/modules/integrations/{models,repository,oauth,service,health,router}.py`
- Test: `apps/backend/tests/integration/integrations/{test_oauth_lifecycle,test_connection_health}.py`, `apps/backend/tests/security/integrations/test_secret_reference_boundary.py`

**Interfaces:**
- Consumes: `SecretVault` and `SecretRef` from Task 5A; audit and tenant-isolation contracts.
- Produces: `IntegrationConnection`; `ConnectorHealth`; OAuth `connect/callback/refresh/revoke`; connector catalog status.

- [ ] **Step 1: Write failing connection/OAuth tests**

  Assert least-privilege scope summary, state/tenant/PKCE verification, duplicate callback handling, opaque credential reference storage, expiry/refresh, revocation, reconnect, health transitions, and complete audit metadata without token values. Reuse the Task 5A redaction and cross-tenant secret-reference assertions instead of retesting a second vault implementation.

- [ ] **Step 2: Run integration and security tests**

  Expect missing connection schema/services while the existing vault tests remain green.

- [ ] **Step 3: Implement the connection and OAuth services**

  Persist only `SecretRef` on a connection; route OAuth callback/refresh/revoke values through `SecretVault`; resolve only for a specific authenticated backend provider call; never decrypt in repositories, routers, runtime tools, model inputs, or frontend responses. Test/reconnect/revoke update health and audit without values, and the same connection service works with the Meta credentials already stored by Task 11.

- [ ] **Step 4: Verify attack cases**

  Tamper with OAuth state/PKCE, replay callbacks, inject a cross-tenant `SecretRef`, revoke during refresh, and inspect exceptions, traces, JSON, logs, frontend responses, and database rows. Expected: fail-closed connection state, no plaintext/token leakage, and every unauthorized resolution denied/audited by the Task 5A vault.

- [ ] **Step 5: Commit**

  Commit `feat: secure connector credentials and lifecycle`.

**Acceptance criteria:** OAuth and API credentials are client-authorized, least-privilege, encrypted, backend-only, revocable, and health-observable.

### Task 23: Implement Google Workspace connector primitives

**Files:**
- Create: `apps/backend/src/agents_factory/modules/integrations/google/{auth,base,calendar,gmail,drive,sheets}.py`
- Create: `docs/integrations/google-workspace.md`
- Test: `apps/backend/tests/contract/integrations/google/`, `apps/backend/tests/integration/integrations/test_google_health.py`

**Interfaces:**
- Produces: Google connector manifests and typed operations used later: Calendar availability/events; Gmail send approval notice; Drive store/read evidence/source; Sheets read/mapped rows and append/update queue rows.

- [ ] **Step 1: Write failing provider contracts with recorded sanitized fixtures**

  Cover OAuth scope mapping, pagination, timezone conversion, rate limits, token expiry, revocation, permission denial, not-found, transient error, Drive MIME/size restrictions, and Sheets header/field mapping.

- [ ] **Step 2: Run contract tests with provider fakes**

  Expect missing adapters.

- [ ] **Step 3: Implement minimal declared operations**

  Each adapter maps provider payloads/errors into `ConnectorResult`; manifests declare only tested operations; no Google Contacts operation is enabled because no v1 workflow requires it yet.

- [ ] **Step 4: Verify least privilege and degradation**

  Health tests show exactly requested scopes; disconnect one Google product and assert unrelated healthy connector operations remain available where separate credentials/scopes permit.

- [ ] **Step 5: Commit**

  Commit `feat: add Google Workspace connector primitives`.

**Acceptance criteria:** Calendar, Gmail, Drive, and Sheets have typed, gated, observable operations; Google Contacts remains absent unless a later approved release requirement activates it.

### Task 24: Implement the Appointments Capability Pack on Google Calendar

**Files:**
- Create: `apps/backend/src/agents_factory/modules/capabilities/appointments/{manifest,models,availability,service,tools}.py`
- Create: `supabase/migrations/*_appointments_config.sql`
- Create: `docs/capabilities/appointments.md`
- Test: `apps/backend/tests/unit/capabilities/appointments/`, `apps/backend/tests/integration/capabilities/test_appointments.py`, `evals/cases/appointments.jsonl`

**Interfaces:**
- Produces: `appointments.check_availability`, `create_appointment`, `get_appointment`, `reschedule_appointment`, `request_cancellation`.

- [ ] **Step 1: Write failing availability/policy tests**

  Cover service duration/buffers, main professional hours, one location, calendar occupancy, lead time, daylight-saving/timezone boundaries, no slot holds, simultaneous booking race, and revalidation immediately before create/reschedule.

- [ ] **Step 2: Write failing action matrix tests**

  Reads LOW; create MEDIUM/Level 1/confirmation; reschedule MEDIUM/Level 2/confirmation; cancellation request HIGH/Level 2/confirmation+approval. Unsupported multiple-resource constraints are rejected as unavailable configuration.

- [ ] **Step 3: Implement manifest, configuration, tools, and connector calls**

  Normalize service/professional/location/time; use `action_id` as provider idempotency metadata; persist external reference; generate immediate confirmation, one configurable reminder, attendance confirmation, reschedule option, and cancellation-request updates through template policy.

- [ ] **Step 4: Verify race and replay**

  Attempt two bookings for the same slot, replay create/reschedule jobs, and run `appointments.jsonl` through Eval Runner v0. Expected: availability revalidation prevents double booking where provider state reveals conflict, each action has one external result, no temporary hold is created, and the capability behavior graders pass.

- [ ] **Step 5: Commit**

  Commit `feat: add Google Calendar appointments capability`.

**Acceptance criteria:** All five required appointment operations obey identity/risk/confirmation/approval rules and the single-professional/location resource model.

### Task 25: Implement WooCommerce and Google Sheets Order connectors

**Files:**
- Create: `apps/backend/src/agents_factory/modules/integrations/woocommerce/{auth,client,manifest}.py`
- Create: `apps/backend/src/agents_factory/modules/integrations/google/orders_sheet.py`
- Create: `docs/integrations/{woocommerce,google-sheets-orders}.md`
- Test: `apps/backend/tests/contract/integrations/test_woocommerce.py`, `apps/backend/tests/contract/integrations/test_orders_sheet.py`

**Interfaces:**
- Consumes: Task 22 connection lifecycle and Task 5A `SecretVault`/`SecretRef`.
- Produces: connector operations for order find/status/tracking/items/delivery, shipping/contact update, note, and cancellation request only where each binding declares support.

- [ ] **Step 1: Write failing contract tests**

  Cover order/customer matching, pagination, status normalization, tracking absence, partial field support, write conflict, already-shipped cancellation, provider timeout, API-key auth encryption, Sheets mapping errors, and operation capability declaration.

- [ ] **Step 2: Run adapter contract tests**

  Expect missing clients/manifests.

- [ ] **Step 3: Implement typed provider adapters**

  WooCommerce resolves scoped HTTPS API credentials from its opaque `SecretRef` only inside the backend request and uses idempotency metadata where supported; Sheets uses explicit tenant-approved field mappings and compare-before-write. Each adapter returns normalized reason codes and uncertainty classification.

- [ ] **Step 4: Verify unsupported-operation gating**

  Bind a read-only Sheet and assert update/note/cancel tools do not enter AgentSpec/runtime; bind WooCommerce with tested writes and assert only those tools appear.

- [ ] **Step 5: Commit**

  Commit `feat: add WooCommerce and Sheets order adapters`.

**Acceptance criteria:** Provider differences remain behind connector contracts and cannot cause the agent to offer unsupported writes.

### Task 26: Implement the Orders Capability Pack and issue flows

**Files:**
- Create: `apps/backend/src/agents_factory/modules/capabilities/orders/{manifest,models,service,tools,issues}.py`
- Create: `docs/capabilities/orders.md`
- Test: `apps/backend/tests/unit/capabilities/orders/`, `apps/backend/tests/integration/capabilities/test_orders.py`, `evals/cases/orders.jsonl`

**Interfaces:**
- Produces required order read/write operation names and issue flows `missing_order`, `wrong_product`, `damaged_product`, `delivery_delay`, `create_claim`.

- [ ] **Step 1: Write failing operation/risk tests**

  Reads are LOW and generally Level 1; contact/address changes MEDIUM/Level 2+confirmation; cancellation request HIGH/Level 2+confirmation+approval. Bind confirmations to normalized order/resource/field values.

- [ ] **Step 2: Write connector-parity and issue-flow tests**

  Execute identical read scenarios through WooCommerce and Sheets; assert normalized customer result. Issue flows collect required identifiers/evidence and hand off case creation to the Cases contract without promising a resolution.

- [ ] **Step 3: Implement capability services/tools**

  Resolve order/customer authorization before reads/writes; call only declared connector operations; map failures to safe retry/status/case behavior; revalidate order state before an approved cancellation.

- [ ] **Step 4: Verify outage isolation and idempotency**

  Disable one order binding, replay updates/notes/cancellation requests, and run `orders.jsonl` through Eval Runner v0. Expected: knowledge/appointments continue, each operation has one durable action/external effect, and connector-neutral behavior graders pass.

- [ ] **Step 5: Commit**

  Commit `feat: add connector-neutral orders capability`.

**Acceptance criteria:** All required read/write/issue flows work through supported bindings with exact default risk rules and localized degradation.

### Task 27: Implement multimodal normalization and tenant-scoped evidence storage

**Files:**
- Create: `supabase/migrations/*_media_evidence.sql`
- Create: `apps/backend/src/agents_factory/modules/media/{contracts,storage,voice,image,pdf,location,contact,video,service}.py`
- Test: `apps/backend/tests/unit/media/`, `apps/backend/tests/integration/media/test_media_pipeline.py`, `apps/backend/tests/security/test_media_isolation.py`

**Interfaces:**
- Produces: `StoredMedia`; `NormalizedMediaObservation`; `OpenAISpeechToTextProvider`; normalized text/image/PDF/location/contact inputs; video metadata for human review.

- [ ] **Step 1: Write failing type/size/security tests**

  Cover MIME sniffing versus claimed type, malware-scan hook result, file/tenant paths, signed access expiry, retention metadata, duplicate content, corrupted media, and cross-tenant object IDs.

- [ ] **Step 2: Write modality tests**

  Voice uses `gpt-4o-mini-transcribe` with Spanish/English/business vocabulary context and records word error rate, p50/p95 latency, and cost against the fixture corpus; image uses `OpenAIImageObservationProvider(model="gpt-5.6-luna")` and returns a schema-constrained workflow observation without tools; PDF uses parser output; location/contact preserve structured fields; video stores privately with no automated advanced analysis; every response remains text.

- [ ] **Step 3: Implement the Media Processor boundary**

  Download through `WhatsAppProvider`, validate/store privately, persist provenance, invoke only the modality-specific provider, and attach normalized observation to the inbound message. Record usage/cost and classify processing failures without discarding original evidence.

- [ ] **Step 4: Verify retention and isolation**

  Run replay, signed URL expiry, delete, and tenant attack tests. Expected: one media record per provider object, no public bucket path, no video reasoning job, and transcript/observation never raises identity level.

- [ ] **Step 5: Commit**

  Commit `feat: normalize inbound media and evidence`.

**Acceptance criteria:** All required inbound modalities are accepted through explicit processors, original/evidence data is tenant-scoped, and v1 output remains text-only.

### Task 28: Implement Returns & Claims with conservative backoffice workflow

**Files:**
- Create: `apps/backend/src/agents_factory/modules/capabilities/returns_claims/{manifest,models,classifier,completeness,service,tools}.py`
- Create: `docs/capabilities/returns-claims.md`
- Test: `apps/backend/tests/unit/capabilities/returns_claims/`, `apps/backend/tests/integration/capabilities/test_returns_claims.py`, `evals/cases/returns_claims.jsonl`

**Interfaces:**
- Produces: identify, classify, collect evidence, validate completeness/policy, create case, communicate status/result; standardized Google Sheets queue + Drive evidence + Gmail notification destination.

- [ ] **Step 1: Write failing classification/completeness tests**

  Cover wrong product, damaged, incomplete, not received, late, nonconformity, and return request; require description, relevant order/customer/item/date fields, available media, and requested resolution according to class/policy.

- [ ] **Step 2: Write forbidden-outcome tests**

  Assert the capability cannot approve a return, refund, issue credit, or promise acceptance; requested resolution is recorded as a request, not a decision.

- [ ] **Step 3: Implement collection and case handoff**

  Reuse media/evidence, knowledge policy validation, Orders references, and Connector manifests; create/update one case through the deduplication contract; for no-CRM tenants write queue/status to Sheets, evidence to Drive, and notice to Gmail.

- [ ] **Step 4: Verify incomplete and duplicate flows**

  Send partial evidence over multiple messages, repeat the request, and run `returns_claims.jsonl` through Eval Runner v0. Expected: one case evolves toward `READY_FOR_REVIEW`, missing fields are requested, no autonomous business approval occurs, and every forbidden-outcome grader passes.

- [ ] **Step 5: Commit**

  Commit `feat: add conservative returns and claims capability`.

**Acceptance criteria:** All supported issue classes reach a reviewable case with complete evidence/provenance and no autonomous refund/return approval.

**Milestone 5 acceptance:** Google Workspace, WooCommerce, Google Sheets, and Meta expose only declared operations; Appointments, Orders, and Returns & Claims pass their risk/identity/eval matrices through Eval Runner v0; multimodal evidence is normalized and tenant-isolated; one connector outage degrades only affected operations where practical. No Generic REST adapter, auth flow, client, webhook, or hidden route exists in the v1 release.

---

## Phase 4 — Milestone 6: Cases, Approvals, and Human Operations

### Task 30: Implement case lifecycle, deduplication, reopen, priority, and Response Targets

**Files:**
- Create: `supabase/migrations/*_cases.sql`
- Create: `apps/backend/src/agents_factory/modules/cases/{models,repository,state_machine,deduplication,priority,targets,service,router}.py`
- Test: `apps/backend/tests/unit/cases/`, `apps/backend/tests/integration/cases/test_case_workflows.py`, `apps/backend/tests/security/test_case_isolation.py`

**Interfaces:**
- Produces: case states defined in Architecture Contracts; `CasePriority = LOW | NORMAL | HIGH | CRITICAL`; `TargetStatus = ON_TRACK | APPROACHING_TARGET | OVERDUE`; `CaseService.find_or_create`, `transition`, `status`.

- [ ] **Step 1: Write failing state-machine tests**

  Cover canonical flow, every additional state, invalid skips, actor/reason evidence, `RESOLVED` versus `CLOSED`, configurable 72-hour close, same-case `REOPENED` during window, and new case after closed/outside window.

- [ ] **Step 2: Write failing dedupe/priority/target tests**

  Use `(tenant_id, customer_id, capability, case_type, resource_id)` plus material-equivalence rules; status questions return the existing case; deterministic priority rules win over LLM interpretation; target timers use tenant configuration and produce approaching/overdue events.

- [ ] **Step 3: Implement repository and services**

  Lock the dedupe key transactionally; append case events; link actions/approvals/evidence; expose customer-safe status; keep conversation `AI_ACTIVE` while a case is `PENDING_APPROVAL` unless an explicit handoff changes control.

- [ ] **Step 4: Verify concurrency and isolation**

  Submit equivalent case requests concurrently and from another tenant. Expected: one case for the owner, no cross-tenant information, and a status response creates no duplicate.

- [ ] **Step 5: Commit**

  Commit `feat: add deterministic case management`.

**Acceptance criteria:** Cases deduplicate, reopen, prioritize, and track operational targets exactly as specified without conflating workflow and conversation control.

### Task 31: Implement approval routes, requests, first-response decisions, and secure OTP verification

**Files:**
- Create: `supabase/migrations/*_approvals.sql`
- Create: `apps/backend/src/agents_factory/modules/approvals/{models,repository,routes,tokens,otp,service,router}.py`
- Create: `apps/backend/src/agents_factory/modules/integrations/google/approval_mailer.py`
- Test: `apps/backend/tests/unit/approvals/`, `apps/backend/tests/integration/approvals/test_first_response.py`, `apps/backend/tests/security/test_approval_security.py`

**Interfaces:**
- Produces: `ApprovalRoute(capability, action, authorized_emails, strategy="first_response")`; `ApprovalRequest`; `ApprovalDecision`; one-time link token digest; OTP challenge digest; `ApprovalService.decide`.

- [ ] **Step 1: Write failing route and request tests**

  Assert each HIGH action has a valid route; one/multiple authorized email addresses are supported; request is bound to tenant/action/parameter digest/expiry; Gmail notice contains a temporary single-use link but no OTP.

- [ ] **Step 2: Write failing security/concurrency tests**

  Cover token tampering, expired/used link, OTP sent only to authorized email, hashed OTP with attempt/expiry limits, OTP absent from logs/traces, approve/reject race, and IP/user-agent audit minimization.

- [ ] **Step 3: Implement first-valid-response transaction**

  Lock the approval row; verify link and OTP; accept the first authorized unexpired decision; invalidate every remaining link/challenge; record decision metadata and a structured reason/result request; never execute from the approval HTTP transaction.

- [ ] **Step 4: Verify**

  Race approval and rejection from two authorized addresses. Expected: exactly one decision wins, later attempts report closed without leaking the winner’s sensitive metadata, and one execution outbox job is emitted only for approved state.

- [ ] **Step 5: Commit**

  Commit `feat: add secure first-response approvals`.

**Acceptance criteria:** High-risk operations have configured, auditable, temporary-link plus email-OTP approval and expired/rejected requests never execute.

### Task 32: Build the secure approval page and customer-safe decision result contract

**Files:**
- Create: `apps/control-plane/app/approval/[token]/{page,actions}.tsx`
- Create: `apps/control-plane/components/approval/{otp-form,decision-form,result}.tsx`
- Create: `apps/backend/src/agents_factory/modules/approvals/result_schema.py`
- Test: `apps/control-plane/tests/e2e/approval.spec.ts`, `apps/backend/tests/contract/test_approval_result.py`

**Interfaces:**
- Produces: public token-bound approval surface with no platform-admin session requirement; structured `DecisionResult(status, reason_code, customer_safe_explanation, next_actions)`.

- [ ] **Step 1: Write failing browser and schema tests**

  Test link landing without disclosing customer secrets, email confirmation, OTP challenge, approve/reject confirmation, first-response closed state, expiry, keyboard/mobile accessibility, cache prevention, and sanitized customer explanation/allowed next-action codes.

- [ ] **Step 2: Run Playwright and contract tests**

  Expect route/schema failures.

- [ ] **Step 3: Implement the minimal one-purpose surface**

  Set `Cache-Control: no-store`, strict CSP/referrer policy, CSRF/origin protection, rate limits, generic invalid/expired responses, and server actions calling approval endpoints. Do not expose Control Plane navigation, raw connector results, or bare boolean decisions.

- [ ] **Step 4: Verify security headers and one-time behavior**

  Reopen/back/refresh/share a consumed link and inspect browser/network logs. Expected: no OTP/token in logs/referrer/history content, and every subsequent decision is refused.

- [ ] **Step 5: Commit**

  Commit `feat: add secure backoffice approval surface`.

**Acceptance criteria:** An authorized reviewer can securely decide from a responsive single-purpose page and the resulting customer message has structured, safe semantics.

### Task 33: Revalidate approved actions, execute safely, and notify the customer automatically

**Files:**
- Create: `workers/agent-worker/src/agent_worker/approval_jobs.py`
- Create: `apps/backend/src/agents_factory/modules/approvals/execution.py`
- Modify: `apps/backend/src/agents_factory/modules/actions/service.py`
- Test: `apps/backend/tests/integration/approvals/test_revalidation_execution.py`, `apps/backend/tests/integration/approvals/test_customer_notification.py`, `evals/cases/approval_results.jsonl`

**Interfaces:**
- Consumes: `ApprovalDecision`, `ActionService`, connector revalidation, outbound templates.
- Produces: one `DecisionResult`; one action terminal state; one automatic WhatsApp result notification with delivery status.

- [ ] **Step 1: Write failing delayed-execution tests**

  Cover approved and still valid, order already shipped, appointment already cancelled, connector outage, ambiguous write result, duplicate execution job, customer conversation `HUMAN_ACTIVE`, and expired approval before worker starts.

- [ ] **Step 2: Run integration tests and `approval_results.jsonl` through Eval Runner v0**

  Expect missing execution coordinator.

- [ ] **Step 3: Implement revalidate-execute-notify**

  Reload action/AgentSpec/connector; verify approval digest and current preconditions; transition to `EXECUTING`; execute idempotently; create structured success/rejection/failure/uncertainty result; enqueue customer notification. If `HUMAN_ACTIVE`, queue the approved structured update according to handoff policy without letting AI reply.

- [ ] **Step 4: Verify audit reconstruction**

  Reconstruct customer request → identity → confirmation → approval → revalidation → execution → notification → delivery from IDs/timestamps, then run the approval-result cases through Eval Runner v0. Expected: no false success, no duplicate external or WhatsApp side effect, and deterministic result graders pass.

- [ ] **Step 5: Commit**

  Commit `feat: execute approved actions with revalidation`.

**Acceptance criteria:** Approval is necessary but not sufficient: current state is revalidated, outcome is safely structured, and the customer is notified automatically and observably.

### Task 34: Implement Live Human Handoff and response-surface gating

**Files:**
- Create: `supabase/migrations/*_handoffs.sql`
- Create: `apps/backend/src/agents_factory/modules/handoffs/{models,surfaces,policy,service,router}.py`
- Test: `apps/backend/tests/unit/handoffs/`, `apps/backend/tests/integration/handoffs/test_control_flow.py`, `apps/backend/tests/security/test_handoff_response_suppression.py`

**Interfaces:**
- Produces: `HumanResponseSurface = WHATSAPP_COEXISTENCE | EXTERNAL_INBOX`; handoff config; transitions `AI_ACTIVE → AWAITING_HUMAN → HUMAN_ACTIVE`; default 12-hour inactivity close.

- [ ] **Step 1: Write failing enablement/trigger tests**

  Deny enabling without a verified surface; allow eligible Coexistence or supported external surface; trigger on explicit human request, mandatory risk escalation, repeated integration failure, unresolved/uncertain consequential action; do not trigger on ambiguous help, frustration alone, or routine `PENDING_APPROVAL`.

- [ ] **Step 2: Write failing silence/availability tests**

  Assert waiting copy never promises an active human when unavailable; `HUMAN_ACTIVE` stores all events and suppresses runtime/outbound AI; inactivity close uses tenant policy; next inbound returns to AI according to session rules.

- [ ] **Step 3: Implement explicit surface verification and policy**

  Handoff records requested reason/surface/actor/timestamps; provider/external events activate/end human control; API-only tenants cannot advertise or enter live handoff. Optional tenant support hours/timezone control availability copy and routing without promising an online human. Backoffice approvals remain available regardless of handoff configuration.

- [ ] **Step 4: Verify race cases**

  Race an AI job with human activation and a delayed outbound send. Expected: final authority check suppresses both AI response paths and audit shows why.

- [ ] **Step 5: Commit**

  Commit `feat: gate and enforce live human handoff`.

**Acceptance criteria:** Live chat authority and backoffice review are separate; API-only tenants never receive a false handoff promise; AI is silent while a human owns the conversation.

### Task 35: Add scheduler policies for reminders, case closure/targets, expiry, and retention

**Files:**
- Create: `workers/scheduler/src/scheduler/{appointment_jobs,case_jobs,approval_jobs,retention_jobs}.py`
- Create: `apps/backend/src/agents_factory/modules/observability/scheduled_events.py`
- Test: `apps/backend/tests/integration/scheduler/`, `apps/backend/tests/unit/scheduler/test_no_pending_spam.py`

**Interfaces:**
- Produces: deterministic scheduled outbox intents for one appointment reminder, attendance confirmation, case auto-close/reopen window, target alerts, approval/action expiry, handoff inactivity, and retention cleanup.

- [ ] **Step 1: Write failing clock-controlled tests**

  Use frozen time for timezone/daylight boundaries, configurable reminder, 72-hour case close, 12-hour handoff close, approval expiry, approaching/overdue thresholds, retry idempotency, and tenant retention values.

- [ ] **Step 2: Add explicit negative notification tests**

  Assert no periodic “still pending” WhatsApp reminder for `PENDING_APPROVAL`; proactive updates occur only on meaningful state change or required customer information and use approved templates when policy requires.

- [ ] **Step 3: Implement schedule scan and outbox creation**

  Claim due rows safely, create deterministic idempotency keys, reevaluate current state before emitting, and audit each schedule decision. Retention deletes/minimizes by data class and records aggregate counts without personal content.

- [ ] **Step 4: Verify replay and time jumps**

  Run scheduler twice for the same interval and advance clocks across closure/expiry boundaries. Expected: one intended event per state transition and zero periodic pending-case messages.

- [ ] **Step 5: Commit**

  Commit `feat: schedule lifecycle and retention policies`.

**Acceptance criteria:** Time-driven jobs emit one auditable event per due state transition, honor tenant timing/retention configuration, and never send periodic pending-case messages.

**Milestone 6 acceptance:** Cases follow the canonical lifecycle/dedup/priority/targets; approvals use link+OTP+first response and revalidation; decision results reach WhatsApp safely; handoff requires a real surface and silences AI; scheduled communications and retention are idempotent and policy-compliant.

---

## Phase 4 — Cross-Cutting Usage Foundation

### Task 36: Implement usage, cost attribution, quotas, and technical guardrails

**Files:**
- Create: `supabase/migrations/*_usage_costs.sql`
- Create: `apps/backend/src/agents_factory/modules/usage/{models,pricing,recorder,aggregates,guardrails,router}.py`
- Test: `apps/backend/tests/unit/usage/`, `apps/backend/tests/integration/usage/test_attribution.py`, `apps/backend/tests/integration/usage/test_guardrails.py`

**Interfaces:**
- Produces: usage records by tenant/run/conversation; model/input/cached/reasoning/output tokens, request count, LLM/WhatsApp/tool cost, storage/infrastructure allocation, latency; cost aggregates and guardrail decisions consumed by Milestone 7 dashboards.

- [ ] **Step 1: Write failing attribution/pricing tests**

  Cover known/unknown provider usage, versioned effective-date price tables, cached/reasoning tokens, WhatsApp template cost metadata, external API costs, storage allocation, currency/rounding, and every dashboard dimension including estimated gross margin.

- [ ] **Step 2: Write failing guardrail tests**

  Cover configurable message/conversation/token-cost/storage/concurrency/tool-call quotas, 70/85/100 alerts, grace/overage at 100 rather than silent shutdown, plus hard max tool calls/retries/model tokens/concurrent runs/rate limits that terminate loops safely.

- [ ] **Step 3: Implement ledger and preflight/after-use recording**

  Record raw measured units and pricing version; derive cost in aggregates; evaluate commercial guardrails before runs and update after usage; enforce technical hard limits in runtime/queue/services regardless of commercial grace.

- [ ] **Step 4: Verify tenant attribution and anomaly path**

  Run two tenants concurrently and inject a runaway tool loop. Expected: every unit belongs to the correct tenant, hard limit stops the loop, an alert appears, and normal grace behavior is distinguishable from technical denial.

- [ ] **Step 5: Commit**

  Commit `feat: attribute costs and enforce usage guardrails`.

**Acceptance criteria:** Tokens/costs/latency are attributable and commercially reportable before their Control Plane views are built; technical limits prevent runaway execution without silently cutting service at a billing milestone.

---

## Phase 4 — Milestone 7: Control Plane Operational UX

### Task 37: Create the responsive navigation, design primitives, and operational dashboard

**Files:**
- Create: `apps/control-plane/components/{layout,forms,status,data-table,empty-state,error-state}.tsx`
- Create: `apps/control-plane/app/(authenticated)/{page.tsx,dashboard/page.tsx}`
- Create: `apps/backend/src/agents_factory/modules/observability/dashboard.py`
- Test: `apps/control-plane/tests/unit/components/`, `apps/control-plane/tests/e2e/dashboard.spec.ts`

**Interfaces:**
- Produces canonical navigation: Dashboard, Tenants, Agents, Capabilities, Integrations, Knowledge, Conversations, Cases, Evals, Usage & Costs, Operations, Settings.

- [ ] **Step 1: Write failing dashboard/browser tests**

  Require mobile/desktop navigation, keyboard/focus behavior, loading/empty/error states, and answers to: agents operating, breakages, critical overdue cases, integration health, and usage/cost.

- [ ] **Step 2: Run component/Playwright tests**

  Expect missing layout/dashboard.

- [ ] **Step 3: Implement server-rendered admin shell and summarized API**

  Use business labels rather than internal queue/model jargon; every health/status badge links to a filtered operational detail; preserve correlation IDs in error support details without exposing secrets.

- [ ] **Step 4: Verify accessibility and responsive behavior**

  Run axe checks at phone/tablet/desktop widths and simulate partial API failures. Expected: dashboard remains usable and identifies stale/unknown data.

- [ ] **Step 5: Commit**

  Commit `feat: add operational control plane shell`.

**Acceptance criteria:** A platform admin can identify operational health, overdue work, integration issues, and cost at a glance.

### Task 38: Implement Tenant detail and Agent configuration screens

**Files:**
- Create: `apps/control-plane/app/(authenticated)/tenants/{page.tsx,new/page.tsx,[tenantId]/layout.tsx}`
- Create: tenant tabs `overview`, `agent`, `capabilities`, `integrations`, `knowledge`, `conversations`, `cases`, `usage`, `settings`
- Create: `apps/control-plane/components/agents/{persona-form,language-form,version-banner}.tsx`
- Test: `apps/control-plane/tests/e2e/tenant-agent.spec.ts`

**Interfaces:**
- Consumes: tenant and AgentSpec APIs.
- Produces: tenant create/edit; Draft Agent Instance; persona/name/tone/formality/locale/languages/vocabulary/greeting; version-aware edits.

- [ ] **Step 1: Write failing tenant/agent flow**

  Create a tenant with company/legal/industry/timezone/locale; create Agent Customer Service Draft; configure permitted persona fields; verify quick options preview and immutable Production banner.

- [ ] **Step 2: Run Playwright test**

  Expect missing pages/forms.

- [ ] **Step 3: Implement forms with schema-derived validation**

  Every Production-affecting edit creates or updates a Draft; unsupported language/product/runtime options are absent; no YAML/code editor exists.

- [ ] **Step 4: Verify resumability and stale writes**

  Reload midway and edit from two sessions. Expected: saved Draft resumes and optimistic concurrency prevents silent overwrite.

- [ ] **Step 5: Commit**

  Commit `feat: configure tenants and agent drafts`.

**Acceptance criteria:** Base tenant/agent configuration is business-friendly, version-aware, and limited to approved v1 fields.

### Task 39: Implement the canonical 12-step resumable onboarding wizard

**Files:**
- Create: `apps/control-plane/app/(authenticated)/tenants/[tenantId]/onboarding/[step]/page.tsx`
- Create: `apps/control-plane/components/onboarding/{wizard,step-status,validation-summary,test-action}.tsx`
- Create: `apps/backend/src/agents_factory/modules/tenants/onboarding.py`
- Test: `apps/backend/tests/unit/tenants/test_onboarding_status.py`, `apps/control-plane/tests/e2e/onboarding.spec.ts`

**Interfaces:**
- Produces exact steps: Company; Agent; Capabilities; Integrations; Knowledge & Conflict Review; Policies & Identity; Human Operations; Approval Routes; WhatsApp; Test; Quality Gate; Production.

- [ ] **Step 1: Write failing step-state tests**

  For each step define instructions, required fields, validation, current status, test actions, blocking errors, warnings, and internal documentation links. Assert direct navigation, resume, completed-step regression after config change, and dependency-based blocking.

- [ ] **Step 2: Run service and browser tests**

  Expect missing step engine/UI.

- [ ] **Step 3: Implement status from domain facts, not a mutable checkbox**

  Derive completion from tenant/AgentSpec/connector/knowledge/policy/approval/WhatsApp/test records; warn on optional features; block Production on required failures; classify unsupported needs as Standard, Custom Connector, Custom Workflow, or New Capability.

- [ ] **Step 4: Verify the Standard path**

  Complete the Standard fixture through the first ten steps, leave/re-enter at each step, and change an upstream capability. Expected: relevant downstream checks become stale/blocked, Quality Gate and Production remain visibly unavailable until Task 45, and progress across all 12 displayed steps is honest.

- [ ] **Step 5: Commit**

  Commit `feat: add canonical tenant onboarding wizard`.

**Acceptance criteria:** A standard tenant can be provisioned by configuration through the exact approved wizard and progress survives interruptions without hiding blockers.

### Task 40: Build Capability, Integration, Policy, Identity, Human, and Approval configuration UX

**Files:**
- Create pages/components under `apps/control-plane/app/(authenticated)/{capabilities,integrations,tenants/[tenantId]}`
- Create: `apps/control-plane/components/configuration/{capability-card,connector-card,risk-matrix,identity-matrix,handoff-form,approval-route-form}.tsx`
- Test: `apps/control-plane/tests/e2e/configuration.spec.ts`

**Interfaces:**
- Consumes: registries, health, policy, identity, handoff, approval APIs.
- Produces: enable/disable capability Draft changes; connector connect/test/reconnect/revoke; scope/operation summaries; stricter tenant policy; response-surface-gated handoff; high-risk route completeness.

- [ ] **Step 1: Write failing configuration flow tests**

  Assert unsupported connector operations are visibly unavailable, coming-later catalog entries cannot connect, tenant policy cannot weaken defaults, handoff toggle is disabled without surface, and high-risk action matrix highlights missing routes.

- [ ] **Step 2: Run Playwright tests**

  Expect missing screens.

- [ ] **Step 3: Implement guided forms and health actions**

  Render manifests and schemas through reviewed components, not arbitrary code; show status, last health check, operations, permissions/scopes, and test/reconnect/revoke; create Draft on change.

- [ ] **Step 4: Verify failure recovery**

  Simulate revoked OAuth, failed health, invalid field mapping, and restored connection. Expected: affected operations/wizard status update without hiding healthy capabilities.

- [ ] **Step 5: Commit**

  Commit `feat: configure capabilities policies and integrations`.

**Acceptance criteria:** Platform configuration is forms/toggles/mappings/tests, and safety minima or unsupported operations cannot be bypassed through UI/API.

### Task 41: Build Knowledge source, proposal, conflict, diff, and version UX

**Files:**
- Create: `apps/control-plane/app/(authenticated)/knowledge/` and tenant Knowledge tab pages
- Create: `apps/control-plane/components/knowledge/{source-form,authority-badge,proposal-review,conflict-review,version-diff}.tsx`
- Test: `apps/control-plane/tests/e2e/knowledge-review.spec.ts`

**Interfaces:**
- Consumes: knowledge source/review/version APIs.
- Produces: source creation/sync; authority assignment; approve/edit/reject; conflict resolution; Draft/Test controls plus fail-closed Quality Gate/Production status completed by Task 45.

- [ ] **Step 1: Write failing end-to-end review flow**

  Upload each supported fixture/source type, assign authority, inspect provenance, edit a proposal, reject another, resolve a conflict, view diff, promote to Test after v0 evals, and verify Production is disabled with the exact missing Quality Gate reason.

- [ ] **Step 2: Run Playwright flow**

  Expect missing pages/components.

- [ ] **Step 3: Implement review-first UX**

  Clearly distinguish source content, AI proposal, admin-approved value, conflicts, Test candidate, and active Production version; disable publish for unresolved critical conflict, stale eval, or unavailable full Quality Gate. Do not treat a passing Eval Runner v0 case as Production evidence.

- [ ] **Step 4: Verify connected-source change**

  Using an immutable active-version fixture, trigger a connected-source diff. Expected: active version badge/content remains unchanged, a new Draft review queue is prominent, and Production remains disabled until Task 45 supplies exact-digest gate evidence.

- [ ] **Step 5: Commit**

  Commit `feat: review and version knowledge in control plane`.

**Acceptance criteria:** No AI-extracted or connected-source change can reach Production without visible human review and exact-version gate.

### Task 42: Build Conversations, Test Console, and review/learning UX

**Files:**
- Create: `apps/control-plane/app/(authenticated)/{conversations,test-console}/`
- Create: `apps/control-plane/components/conversations/{timeline,trace-panel,review-labels}.tsx`
- Create: `apps/control-plane/components/test-console/{simulator,run-inspector,mode-selector}.tsx`
- Test: `apps/control-plane/tests/e2e/test-console.spec.ts`, `apps/control-plane/tests/e2e/conversation-review.spec.ts`

**Interfaces:**
- Produces Test modes `SANDBOX_SIMULATED | REAL_TEST_ENVIRONMENT`; inspector fields AgentSpec, intent/capability, identity, tools, sources, action, approval, usage/cost, latency, traces; review categories/labels from spec.

- [ ] **Step 1: Write failing console/review tests**

  Simulate a conversation and inspect every required field; assert Sandbox blocks production writes; Real Test requires test tenant/accounts; filter categories AI resolved, human handoff, tool failure, policy violation, complaint, high-cost conversation, and flagged conversation; apply labels correct, incorrect, unsafe, knowledge problem, integration problem, and model reasoning problem; export a minimized/anonymized failure as a schema-valid Eval Runner v0 Draft case.

- [ ] **Step 2: Run browser tests**

  Expect missing console/review pages.

- [ ] **Step 3: Implement trace-correlated views and safe execution mode**

  Every run displays exact AgentSpec/Knowledge digests; Sandbox injects fake connector executors and refuses Production binding; conversation review links messages/tools/actions/approvals/costs without revealing secret values. Draft regression export writes a sanitized v0-compatible JSONL candidate for review; persistent learning-loop registration and Quality Gate inclusion remain owned by Task 45.

- [ ] **Step 4: Verify accidental-write prevention**

  Attempt a real cancellation/update in Sandbox. Expected: simulated action/result is visible, external fake records intent, and production connector call count is zero.

- [ ] **Step 5: Commit**

  Commit `feat: add safe test console and review loop`.

**Acceptance criteria:** Admins can inspect simulated/real-test behavior, export minimized schema-valid regression cases that run through Eval Runner v0, and avoid accidental Production writes; only Task 45 promotes reviewed cases into persisted release-gate evidence.

### Task 43: Build Cases, Usage & Costs, Operations, Evals, and Settings views

**Files:**
- Create pages under `apps/control-plane/app/(authenticated)/{cases,usage-costs,operations,evals,settings}`
- Create: `apps/control-plane/components/{cases,usage,operations,evals}/`
- Test: `apps/control-plane/tests/e2e/operations.spec.ts`, `apps/control-plane/tests/e2e/cases.spec.ts`

**Interfaces:**
- Consumes: available cases/approval, usage, integration health, and job/DLQ APIs; typed availability contracts for incident, deployment, and Quality Gate APIs completed by Tasks 44, 45, and 47.
- Produces: case priority/lifecycle/target/reviewer views; cost dimensions; queue/worker/DLQ/integration views; audited DLQ retry/discard/resolve actions; explicit fail-closed unavailable states for M8 incident, deployment, and Quality Gate data.

- [ ] **Step 1: Write failing operational flows**

  Filter overdue CRITICAL cases, inspect approval status, view costs by conversation/case/action/tenant and revenue versus variable cost, inspect degraded worker/connector, open a DLQ item, execute retry/discard/resolve with confirmation/audit, and verify M8-only incident/deployment/Quality Gate surfaces show a typed unavailable reason rather than invented data.

- [ ] **Step 2: Run Playwright tests**

  Expect missing pages.

- [ ] **Step 3: Implement business-first views**

  Use pagination and tenant filters; mark data freshness; link all available aggregates to traceable records; require explicit confirmation/reason for DLQ mutation; render M8-only surfaces from explicit availability responses and fail closed when their API is not installed; expose no arbitrary shell/SSH console.

- [ ] **Step 4: Verify no-SSH routine operation**

  Resolve a fixture connector issue, DLQ job, and overdue case solely through Control Plane actions; attempt an unavailable Quality Gate mutation. Expected: complete audit trail for supported actions, explicit refusal for the M8-only action, no fake success, and no terminal use.

- [ ] **Step 5: Commit**

  Commit `feat: add control plane operational workspaces`.

**Acceptance criteria:** All canonical admin destinations exist; implemented M1–M7 domains expose traceable, tenant-filtered data and safe audited mutations, while M8-only incident/deployment/Quality Gate surfaces are honestly unavailable and fail closed until their owning tasks connect them.

**Milestone 7 acceptance:** A platform admin can use the canonical navigation and 12-step wizard to configure, connect, review, test, and operate a standard tenant through responsive guided UX; Quality Gate and Production are visibly fail-closed pending M8; there is no client portal, human inbox, YAML, arbitrary code, or routine SSH requirement.

---

## Phase 5 — Milestone 8: Evals, Hardening, and Production

### Task 44: Implement unified traces, metrics, audit correlation, health, and incident detection

**Files:**
- Create: `supabase/migrations/*_observability.sql`
- Create: `apps/backend/src/agents_factory/modules/observability/{models,tracing,metrics,health,alerts,incidents,router}.py`
- Create: `packages/shared-schemas/events.schema.json`
- Modify: `apps/control-plane/app/(authenticated)/operations/`, `apps/control-plane/components/operations/`
- Test: `apps/backend/tests/integration/observability/test_trace_reconstruction.py`, `apps/backend/tests/unit/observability/test_alerts.py`, `apps/backend/tests/security/test_observability_redaction.py`

**Interfaces:**
- Produces: correlated IDs for Tenant, Conversation, Message, AgentSpec, Knowledge, Capability, Tool, Connector, Action, Approval, Trace, Error, Cost, Timestamp; health checks for WhatsApp, OpenAI, Supabase, Redis, workers, scheduler, connectors.

- [ ] **Step 1: Write failing reconstruction/redaction tests**

  Build one end-to-end fixture and assert it can be reconstructed from correlation IDs while OTPs, credentials, tokens, full sensitive responses, card data, and unnecessary personal data are absent.

- [ ] **Step 2: Write failing alert/incident tests**

  Cover disconnected/reauth connector, queue backlog, missing worker heartbeat, high failure rate, cost anomaly, CRITICAL overdue case, WhatsApp webhook failure, knowledge sync failure, and DLQ growth; debounce/deduplicate repeated symptoms into an incident.

- [ ] **Step 3: Implement distinct log/metric/trace/audit/incident records**

  Emit structured events with tenant/correlation context and bounded payloads; aggregate health without scanning raw content; route alerts to the configured platform operational destination; preserve evidence for safety incidents; replace Task 43's typed incident-unavailable state with traceable incident/health data.

- [ ] **Step 4: Verify degraded dependencies**

  Fault-inject each dependency. Expected: readiness/health identifies component, affected operations fail safely, unrelated operations continue where practical, alert/incident/audit are linked, and no secret leaks.

- [ ] **Step 5: Commit**

  Commit `feat: correlate platform observability and incidents`.

**Acceptance criteria:** Operators can reconstruct important outcomes and detect failures without conflating logs, metrics, traces, audits, or incidents.

### Task 45: Build the executable eval harness and release-blocking Quality Gate

**Files:**
- Modify: `evals/{README.md,run_local.py,graders.py,case_schema.py}`
- Create: `evals/cases/{global,security,tenant_isolation,human_control,failure_handling}.jsonl`
- Create: `apps/backend/src/agents_factory/modules/evals/{models,runner,quality_gate,router}.py`
- Create: `supabase/migrations/*_eval_runs.sql`
- Modify: `apps/backend/src/agents_factory/modules/agent_factory/service.py`, `apps/backend/src/agents_factory/modules/knowledge/publishing.py`
- Modify: `apps/control-plane/app/(authenticated)/{evals,knowledge,conversations}/`, `apps/control-plane/app/(authenticated)/tenants/[tenantId]/onboarding/[step]/page.tsx`
- Test: `apps/backend/tests/unit/evals/test_quality_gate.py`, `apps/backend/tests/integration/evals/test_real_agent_path.py`, `apps/control-plane/tests/e2e/quality-gate.spec.ts`

**Interfaces:**
- Consumes: Eval Runner v0 and case/grader contracts from Task 9A; fail-closed `ProductionQualityGate` port from Task 12; M7 unavailable UI states.
- Produces: global + capability + tenant eval suite; persisted `EvalRun` tied to exact AgentSpec/Knowledge/code versions; `QualityGateDecision`; API/UI evidence; non-zero CLI exit on failure; real Production publication gate.

- [ ] **Step 1: Write failing harness contract tests**

  Preserve compatibility with every v0 case, then require the actual runtime/tool/policy path, isolated/reset durable state per case, structured graders for outputs/tool calls/state/audit/handoff/guardrails, persisted and CLI JSON results, cost/latency, reproducible seed, API authorization, and no grading of volatile IDs/exact prose unless contractual.

- [ ] **Step 2: Encode every required eval category**

  Add conversational, scope, source authority, tool/result, identity, authorization, confirmation, approval, tenant isolation, human control, failure/uncertainty, capability, and tenant-regression cases. Include Spanish/English and multimodal fixtures; allow a reviewed Task 42 Draft case to be registered with sanitization/provenance evidence before it joins a tenant-regression suite.

- [ ] **Step 3: Encode hard blockers exactly**

  Any cross-tenant access, sensitive action without identity/authorization, required confirmation bypass, HIGH approval bypass, secret exposure, AI response while `HUMAN_ACTIVE`, or false success after uncertain write sets Gate result to failed regardless of aggregate score. Other metrics use configured thresholds.

- [ ] **Step 4: Verify exact-version publication gate**

  Implement `ProductionQualityGate` with persisted `QualityGateDecision`; connect AgentSpec/Knowledge publication, the onboarding wizard, Knowledge controls, and Evals view. Run a passing suite, publish the exact candidate in a test environment, change AgentSpec or Knowledge digest, and attempt publish again; expected stale gate rejection. Introduce each critical violation and assert non-zero CLI, visible evidence, and blocked Production.

- [ ] **Step 5: Commit**

  Commit `feat: add release-blocking quality gate`.

**Acceptance criteria:** Task 45 extends rather than replaces Eval Runner v0; Production publishing requires a persisted passing gate for the exact AgentSpec/Knowledge/code inputs; the Control Plane exposes that evidence; and all seven critical failures block unconditionally.

### Task 46: Implement privacy operations, retention, deletion, export, and minimization

**Files:**
- Create: `apps/backend/src/agents_factory/modules/privacy/{models,deletion,export,minimization,router}.py`
- Create: `workers/scheduler/src/scheduler/privacy_jobs.py`
- Create: `docs/security/privacy-retention.md`
- Test: `apps/backend/tests/integration/privacy/`, `apps/backend/tests/security/test_privacy_boundaries.py`

**Interfaces:**
- Produces: tenant-authorized conversation/customer deletion, integration revocation, file/media removal, minimized metrics, and export jobs with audit/legal-hold status.

- [ ] **Step 1: Write failing lifecycle tests**

  Cover default/custom retention classes, deletion across messages/media/vectors/provider references, connector revoke, export manifest/checksums, anonymized aggregate preservation, legal/operational hold, idempotent retry, and no cross-tenant target discovery.

- [ ] **Step 2: Run privacy/security tests**

  Expect missing service/jobs.

- [ ] **Step 3: Implement durable privacy jobs**

  Validate scope/authorization, record requested/started/completed/failed state, delete or minimize in dependency order, revoke external integrations, expire signed links, retain only legally/operationally permitted audit facts, and never put exported content in logs.

- [ ] **Step 4: Verify restore/export implications**

  Execute deletion and export on a full tenant fixture, then run search/retrieval/storage/audit checks. Expected: personal content is gone or minimized, export is complete and tenant-scoped, and aggregate metrics cannot be reidentified by direct IDs.

- [ ] **Step 5: Commit**

  Commit `feat: add privacy and retention operations`.

**Acceptance criteria:** The platform has operational data deletion/revocation/media removal/minimization/export paths and documented defaults, subject to legal review before commercialization.

### Task 47: Harden existing CI and add container, Staging, Production, and rollback delivery

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/{deploy-staging,deploy-production}.yml`
- Create: `infrastructure/docker/{backend,control-plane}.Dockerfile`
- Create: `infrastructure/proxy/Caddyfile`
- Create: `infrastructure/scripts/{deploy,smoke,rollback}.sh`
- Modify: `apps/control-plane/app/(authenticated)/operations/`, `apps/control-plane/components/operations/`
- Modify: `docker-compose.yml`
- Test: `infrastructure/scripts/test_images.sh`, `infrastructure/scripts/smoke.sh`

**Interfaces:**
- Produces: feature branch → PR → automated gates → `main` → versioned images → auto Staging → smoke → GitHub environment manual approval → Production; rollback to prior images/config when schema-compatible.

- [ ] **Step 1: Write failing workflow/image checks**

  Validate pinned actions by commit SHA, minimal permissions, dependency cache keys from lockfiles, no secrets on PRs/logs, migration dry-run, immutable image tags/labels/SBOM, non-root read-only containers, health checks, and no Development data path to Production.

- [ ] **Step 2: Implement CI gates**

  Extend the Task 1A workflow without renaming its required `ci-baseline` result: retain format/lint/type/unit/basic-security gates and add integration, full security/RLS, E2E, full eval, image build, SBOM, and image/dependency vulnerability checks; upload only sanitized test/eval artifacts. Critical component jobs feed the stable required aggregate check.

- [ ] **Step 3: Implement deployment workflows**

  GitHub Actions deploys versioned images to Hostinger over a least-privilege mechanism, runs migrations before app promotion, auto-deploys Staging, runs smoke, and requires explicit protected Production approval. Environment secrets never cross environments; replace Task 43's typed deployment-unavailable state with traceable version/status data and no arbitrary shell surface.

- [ ] **Step 4: Verify Staging and rollback drill**

  Deploy to Staging with test tenant/accounts/numbers, run smoke/E2E, deploy a deliberately failing health version, and roll back. Expected: previous compatible version recovers, deployment/audit metadata is visible, Production was untouched.

- [ ] **Step 5: Commit**

  Commit `ci: add gated staging and production delivery`.

**Acceptance criteria:** All code changes pass automated gates, Staging deploys automatically, Production requires manual approval, and rollback is rehearsed without claiming HA.

### Task 48: Verify backups, restore, secrets rotation, and single-VPS disaster recovery

**Files:**
- Create: `infrastructure/runbooks/{backup-restore,secret-rotation,disaster-recovery}.md`
- Create: `infrastructure/scripts/{backup_manifest,verify_restore,rotate_master_key}.sh`
- Test: `infrastructure/scripts/test_restore_drill.sh`

**Interfaces:**
- Produces: documented RPO/RTO observations from an actual drill; database/configuration/Storage inventory; key rotation procedure; rebuilt VPS procedure.

- [ ] **Step 1: Define the durable asset inventory and failing restore check**

  Include Supabase PostgreSQL, Storage objects (not assumed covered by DB backup), encrypted secrets, deployment/config versions, GitHub repository/images, and required external account mappings; exclude Redis as source of truth.

- [ ] **Step 2: Prepare a Staging backup and isolated restore target**

  Generate checksummed manifests, restore database and Storage into a disposable/test project, provide the master key through environment, rebuild containers from immutable images, and leave Production untouched.

- [ ] **Step 3: Run the restore verification**

  Assert tenant/AgentSpec/Knowledge/action/audit counts and checksums, RLS isolation, media retrieval, secret decryption, pending outbox reconciliation, application readiness, and one sandbox conversation. Record measured duration and gaps.

- [ ] **Step 4: Run a master-key rotation drill**

  Re-encrypt secret payloads under a new version with resumable audit, verify all test connectors, then retire the old key only after completeness check. Ensure neither key enters DB/repo/logs.

- [ ] **Step 5: Commit**

  Commit `docs: verify backup restore and key rotation`.

**Acceptance criteria:** Before a real customer, a clean environment can be restored from durable backups and the master key can rotate; the runbook explicitly states single-VPS availability limitations.

### Task 49: Produce the required product documentation and go-live runbook

**Files:**
- Create/update: `docs/capabilities/*.md`, `docs/integrations/*.md`, `docs/security/{tenant-isolation,secrets,privacy-retention,incident-handling}.md`
- Create: `docs/operations/{deploy,rollback,reconnect,dlq,restore,rotate,incident-response,go-live}.md`
- Create: `docs/client-onboarding-playbook.md`
- Test: `infrastructure/scripts/verify_docs.sh`

**Interfaces:**
- Produces: the seven required documentation sets linked from Control Plane help and README.

- [ ] **Step 1: Write failing documentation coverage/link check**

  Require every capability action/risk/identity/approval/eval, every active v1 connector auth/scope/operation/error, security/retention/incident controls, every operational procedure, the evolving onboarding playbook, the master spec, and this implementation plan; reject broken internal links and undocumented active manifest operations. Generic REST may be named only as unavailable/deferred v1.1 and does not create an active connector document in v1.

- [ ] **Step 2: Generate docs from contracts where deterministic**

  Render action/connector matrices from versioned manifests into checked-in Markdown, then add human-reviewed business/error/operations explanations. Do not advertise unavailable connectors as supported.

- [ ] **Step 3: Complete runbooks with observable commands and rollback points**

  Each runbook states prerequisites, exact safe commands/UI actions, expected signals, audit evidence, rollback/escalation, and forbidden secret handling. Client onboarding mirrors Discovery through Post-Go-Live and Standard/Custom classifications.

- [ ] **Step 4: Verify with a cold-reader rehearsal**

  A platform admin follows reconnect, DLQ, rollback, restore, rotate, and incident exercises in Staging without repository tribal knowledge. Record and fix every ambiguous/missing step.

- [ ] **Step 5: Commit**

  Commit `docs: complete product and operations handbook`.

**Acceptance criteria:** Required product/security/operations/onboarding documentation is version-controlled, contract-consistent, and usable without SSH tribal knowledge.

### Task 50: Run the complete Standard SME release acceptance and first-customer go-live rehearsal

**Files:**
- Create: `evals/cases/release_acceptance.jsonl`
- Create: `docs/operations/release-evidence/v1-release-checklist.md`
- Create: `docs/operations/release-evidence/v1-test-report.md`
- Test: all Standard Verification Commands plus Staging real-provider smoke

**Interfaces:**
- Consumes: every milestone.
- Produces: signed-off evidence package for an exact code image, migration version, AgentSpec digest, Knowledge digest, connector health snapshot, and Quality Gate run.

- [ ] **Step 1: Onboard one representative Standard SME test tenant through the UI**

  First record Discovery output: customer-service use cases/channels, expected WhatsApp volume, process-to-capability mapping, source/system inventory, handoff need/surface, high-risk actions/approvers, Standard classification, responsible contacts, and any unsupported request. Then create tenant/Agent; configure Spanish/English persona; enable Appointments, Orders, Returns & Claims; connect Meta test number, Google Workspace, WooCommerce/Sheets as applicable; ingest/review knowledge; configure identity/policies/approvals/human operations; complete Test and Quality Gate; explicitly publish exact Production version in Staging.

- [ ] **Step 2: Execute the full representative scenario suite**

  Run happy FAQ, scope redirect, language, order reads, confirmed writes, approval/rejection, changed state before approval execution, case create/dedupe/reopen/status, every multimodal type, enabled/disabled handoff, unavailable integration, duplicate webhook, retry/idempotency, abuse/safety, proactive template, and tenant-isolation attacks.

- [ ] **Step 3: Prove all ten additional release criteria**

  Record evidence that duplicates cannot create consequential duplicates; cross-tenant tests fail closed; no AI replies in `HUMAN_ACTIVE`; no HIGH execution lacks approval; approved work revalidates; uncertain writes make no success claim; outages remain localized; knowledge changes do not alter Production; costs/tokens belong to the tenant; and one reviewed Production-like failure becomes an anonymized regression case.

- [ ] **Step 4: Run production-readiness checks**

  Verify health/alerts/DLQ, exact versions, encrypted secret audit, privacy/retention configuration, backup/restore evidence, Staging smoke, rollback compatibility, Meta template status, external legal/privacy review gate, responsible approvers, and first-conversation/cost monitoring assignments.

- [ ] **Step 5: Record explicit release decision**

  If every critical item passes, capture approver/date/version evidence and authorize manual Production deployment; any critical failure keeps the release blocked with owner/reproduction/eval ID. Commit `test: record Agents Factory v1 release evidence`.

**Acceptance criteria:** The exact Staging release has complete, reproducible evidence for the approved E2E flow and all ten additional criteria; any critical failure blocks the release rather than being waived by an aggregate score.

**Milestone 8 acceptance:** All critical gates pass for exact artifacts; the deployment/restore/privacy/observability paths are rehearsed; a Standard SME tenant completes the full approved flow without tenant-specific code; manual Production approval remains the final external action.

---

## Cross-Milestone Acceptance Matrix

| Approved requirement | Primary task(s) | Release evidence |
|---|---|---|
| Private GitHub repository and local laptop copy | 0 | Remote visibility/default branch/HEAD check and clean local worktree |
| Shared multi-tenant data with defense-in-depth isolation | 3, 5, 5A, every migration | pgTAP + repository attack matrix on clean/seeded DB |
| Signed/deduplicated/ordered durable WhatsApp flow | 6–11, 9A | Replay and crash simulation; one action/message + v0 runtime eval |
| Meta Embedded Signup, API-only and eligible Coexistence | 11, 34 | Test account mapping and handoff enablement gate |
| Envelope-encrypted backend-only secrets and rotation | 5A, 11, 22, 48 | Cryptographic/RLS/redaction tests + rotation drill |
| AgentSpec/version lifecycle and runtime replaceability | 9, 12 | JSON schema/digest/immutability/adapter contracts |
| Customer Service Core, persona/scope/language/abuse | 16 | Bilingual global eval suite |
| Identity, authorization, risk, confirmation, approval | 14, 15, 31–33 | Security blockers and full audit reconstruction |
| Knowledge structured/RAG, authority/provenance/change review | 17–21, 41 | Cross-tenant retrieval, conflict, no silent Production change |
| Required connectors and three Capability Packs | 5A, 11, 22–28 | Provider contracts + capability eval/action matrices; no Generic REST executable |
| Inbound multimodal and text-only response | 27 | Modality fixtures; no video analysis/voice response |
| Cases, targets, reopen, no pending spam | 30, 35 | Clock/concurrency/dedup tests |
| Live handoff separate from backoffice review | 31–35 | API-only denial; `HUMAN_ACTIVE` silence; approval independent |
| Canonical private Control Plane and onboarding | 37–43 | Playwright Standard onboarding and no-SSH operations |
| Evals/Quality Gate and learning loop | 9A, 42, 45, 50 | Early executable cases, exact-digest gate, and reviewed failure converted to eval |
| Usage/cost/guardrails | 36 | Two-tenant attribution and runaway-loop test |
| Observability/health/incidents/DLQ | 7, 43, 44 | Fault injection and trace reconstruction |
| Privacy/retention/deletion/export | 35, 46 | Full-fixture privacy tests and documented legal review gate |
| Dev/Staging/Production CI/CD on single VPS | 1A, 47 | Required basic CI from M1, hardened gates, Staging deployment, manual Production, rollback drill |
| Backup/restore before first real customer | 48 | Isolated restore and key-rotation evidence |
| Required documentation set | 49 | Contract-to-doc coverage and cold-reader rehearsal |
| Complete v1 E2E flow and ten release criteria | 50 | Versioned release checklist/test report |

## Quality and Review Gates by Milestone

| Gate | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Format/lint/type/unit | Required | Required | Required | Required | Required | Required | Required | Required |
| Clean migration + RLS matrix | Required | Required | Required | Required | Required | Required | Required | Required |
| Provider/connector contracts | — | Meta | Runtime | Embeddings | All required v1 | Gmail/Meta | API schemas | Real Staging smoke |
| Integration/crash/idempotency | Foundation | Required | Actions | Ingestion/Test candidate | Writes/media | Approval/scheduler | Test Console | Full suite |
| Playwright/accessibility | Auth shell | WhatsApp setup | — | — | — | Approval page | Required | Full onboarding |
| Evals | — | Runner v0 turn smoke | Core/security via v0 | Knowledge via v0 | Capability via v0 | Approval/handoff via v0 | Console export via v0 | Blocking full gate |
| Security/privacy | RLS/auth/secrets | Webhook/HUMAN/Meta refs | Actions | Retrieval/source-ingestion SSRF | Media/provider credentials | Approval | Admin authz | Full + deletion/export |
| Build/deploy/restore | Compose + required basic CI | Worker smoke | — | — | — | — | UI build | Hardened CI/deploy/restore required |

## Self-Review Record — revised 2026-08-15

- **Specification coverage:** Sections 1–48 and the approved 2026-08-14 amendment were checked against every executable v1 task and the Cross-Milestone Acceptance Matrix. No approved v1 requirement lacks an owning task or release check.
- **Scope control:** Every explicit exclusion from Section 3.3 is either named in Scope Exclusions or enforced by a negative test/configuration gate. Generic REST is isolated in the non-executable v1.1 appendix; no executable v1 task introduces it or any other excluded connector, product, runtime, response modality, inbox, billing system, refund path, enterprise topology, or multi-resource booking model.
- **Marker scan:** The only intentional deferred work is the explicitly bounded v1.1 appendix. Executable v1 tasks contain no vague “handle errors/add tests” markers; each names concrete failures, expected outcomes, files, interfaces, verification, commit, and acceptance criteria.
- **Type consistency:** AgentSpec/configuration, conversation, action, identity, risk, case, approval, connector, knowledge, media, and runtime names were compared across definitions and consuming tasks. Canonical state values and tool operation names are consistent.
- **Dependency consistency:** Basic CI begins after locked workspaces; Secrets Foundation precedes Meta/OAuth consumers; Eval Runner v0 precedes all domain case suites; full Quality Gate alone unlocks Production; hardened CI/deployment builds on the required M1 check. Usage/cost APIs precede their dashboard; capability tools consume connector manifests; approvals consume action/identity/policy foundations; Control Plane pages fail closed for M8-owned APIs until those tasks connect them.
- **Execution consistency:** Dependency-safe overlap is not execution authority. Phase 0 plus M1 require the first explicit authorization; every later milestone stops for its own evidence review and explicit approval; Production remains separate.
- **Planning-only check:** This review modified only the implementation plan and the approved dated scope amendment in the local master specification. Git initialization, GitHub creation, dependency installation, scaffolding, migrations, external authorization, deployment, and product implementation remain gated on explicit implementation approval.

## Final Definition of Done

Agents Factory v1 is done only when:

1. The exact release satisfies every executable v1 task and all milestone acceptance gates; the v1.1 appendix is excluded.
2. A Standard SME tenant completes the approved end-to-end flow without tenant-specific code.
3. Every critical Quality Gate failure is demonstrably blocking.
4. The private GitHub `main` branch, versioned container images, deployed Staging version, and local laptop checkout identify the same commit.
5. Backup/restore, rollback, key rotation, privacy operations, DLQ handling, and connector reconnection have been exercised outside Production.
6. The user explicitly authorizes Phase 0 plus Milestone 1, then accepts each milestone review package and explicitly authorizes the next; later, manual Production approval remains separate from every plan/milestone approval.

No executable v1 task in this plan authorizes a public repository, a real-customer production launch, external customer messaging, paid subscription setup, Generic REST, or implementation of any other excluded v1 feature without separate user authorization.

---

## Appendix A — Deferred v1.1 Work (Non-Executable)

This appendix preserves the reviewed design for a possible **v1.1 / Custom Onboarding Foundation**. It is outside the v1 roadmap, milestone gates, Definition of Done, release blockers, and current implementation authority. Do not create any listed file, route, adapter, auth flow, or webhook unless the user separately approves v1.1 scope and an updated execution plan. The generic `Connector` contract and Custom Connector classification remain available in v1; this implementation does not.

### Deferred Task v1.1-1: Implement the Generic REST API/Webhook connector foundation

**Files:**
- Create: `apps/backend/src/agents_factory/modules/integrations/generic_rest/{manifest,schemas,auth,client,webhook}.py`
- Create: `docs/integrations/generic-rest.md`
- Test: `apps/backend/tests/security/integrations/test_generic_rest_ssrf.py`, `apps/backend/tests/contract/integrations/test_generic_rest.py`

**Interfaces:**
- Produces: admin-configured allowlisted base URL, auth secret reference, explicit operation schemas/mappings, idempotency/header policy, normalized webhook input.

- [ ] **Step 1: Write failing security/contract tests**

  Deny localhost, link-local, private/reserved IP resolution, redirect escape, non-HTTPS Production URL, arbitrary headers, dynamic method/path outside manifest, oversized response, secret reflection, and unsigned inbound webhook. Test timeouts/retries/idempotency classifications.

- [ ] **Step 2: Run tests**

  Expect missing foundation.

- [ ] **Step 3: Implement a manifest-driven connector only**

  Allow explicitly configured HTTP method/path/request/response mappings and auth reference; resolve/validate DNS on connect and call; cap body/time; map errors to `ConnectorResult`. Do not add a user-authored code runner or general model-facing HTTP tool.

- [ ] **Step 4: Verify custom-onboarding boundary**

  Demonstrate one fake external order-read operation from a signed manifest; changing business workflow still requires an approved Custom Workflow/New Capability rather than arbitrary REST configuration.

- [ ] **Step 5: Commit**

  Commit `feat: add safe generic REST connector foundation` only under a separately approved v1.1 plan.

**Future v1.1 acceptance criteria:** The Custom Onboarding foundation executes only signed, allowlisted, schema-mapped HTTPS operations and cannot become a model-facing arbitrary HTTP/code execution facility.
