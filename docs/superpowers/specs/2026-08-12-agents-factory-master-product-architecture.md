# Agents Factory — Master Product & Architecture Design Specification

**Date:** 2026-08-12  
**Status:** Approved v1 design — implementation authorized milestone by milestone  
**Initial product:** Agent Customer Service  
**Primary market assumption:** SMEs, WhatsApp-first  
**Architecture style:** Multi-tenant modular monolith with asynchronous workers  
**Initial agent runtime:** OpenAI Agents SDK for Python  
**Initial model target:** `gpt-5.6-luna`, reasoning effort `low`

---

## Approved v1 Scope Amendment — 2026-08-14

The user approved deferring the **generic REST API/Webhook connector foundation for Custom Onboarding** from v1 to **v1.1 / Custom Onboarding Foundation**. This amendment is part of the project source of truth and supersedes only the corresponding requirement in Section 23.1; every other approved v1 product and architecture decision remains unchanged.

v1 retains the generic `Connector` contract, the Custom Connector classification in the Integration Catalog, and the Tenant Extension boundary needed for future connectors, but it must not ship an executable generic REST adapter, configurable auth/client, generic webhook route, or model-facing arbitrary HTTP capability. Implementing that foundation requires separate v1.1 authorization and all of its security controls.

---

## 1. Purpose

Agents Factory is a proprietary platform for creating, configuring, testing, deploying, operating, and improving reusable business agents without building a new codebase for every customer.

The first commercial product is **Agent Customer Service**, a general customer-service agent designed to do more than answer FAQs. Its core value proposition is:

> **Know → Reason → Act**

The agent must be capable of understanding a customer's business request, retrieving approved business knowledge, verifying identity when necessary, executing permitted actions through integrations, requesting customer confirmation or backoffice approval for consequential operations, managing cases, escalating to a human when configured, and recording an auditable result.

The platform must turn client onboarding into **provisioning and configuration of an Agent Instance**, not development of another bespoke chatbot.

---

## 2. Product Principles

1. **Action-oriented, not chatbot-oriented.** The product must execute supported business operations, not merely answer questions.
2. **Configuration over custom code.** A standard client should be onboardable through the Control Plane when their needs are covered by existing Capability Packs and Connectors.
3. **LLM for interpretation; deterministic systems for control.** Identity, authorization, confirmation, approval, state transitions, tenant boundaries, and sensitive execution are enforced by structured backend logic.
4. **Tenant isolation is a platform invariant.** Prompts are never trusted as a security boundary.
5. **Fail closed on uncertainty.** The system must never claim that a consequential action succeeded when its outcome is uncertain.
6. **Production changes are versioned.** Knowledge, policies, capabilities, integrations, and agent configuration move through Draft → Test → Quality Gate → Production.
7. **Operational evidence matters.** Conversations, tool calls, actions, approvals, costs, versions, errors, and important decisions must be attributable and reconstructable.
8. **YAGNI for v1.** The platform is extensible, but v1 does not implement multi-runtime orchestration, a full client portal, a human inbox, automatic refunds, or enterprise-dedicated infrastructure.

---

## 3. Product Boundary

### 3.1 Agents Factory

Agents Factory is the internal platform. It includes:

- Control Plane
- Tenant management
- Agent Factory / Agent Instances
- Capability Registry
- Integration Catalog
- Knowledge management
- Policies and Identity
- Approvals
- Case management
- Conversation review
- Evals / Quality Gate
- Usage and Costs
- Operations / health / incidents
- Versioning and deployments

### 3.2 Agent Customer Service

Agent Customer Service is the first reusable agent product built on Agents Factory.

It contains:

- Customer Service Core
- Capability Packs
- Tenant-specific configuration
- Tenant Extensions where required
- Integration bindings
- Knowledge bindings
- Policies and approval routes

### 3.3 Out of v1 product scope

The following are explicitly not required for v1:

- Full Client Portal
- Agents Factory human inbox
- Subscription billing / payment collection
- Multiple commercial agent products
- Multi-runtime support
- Advanced multi-agent orchestration
- Shopify connector
- HubSpot connector unless a real customer makes it a release requirement
- Salesforce connector
- Generic REST API/Webhook connector foundation for Custom Onboarding (deferred to v1.1)
- Multiple simultaneous booking resources such as room + equipment + professional
- Automatic refunds or credits
- Voice responses
- Advanced video understanding
- Full WhatsApp template editor
- Enterprise dedicated runtime/database/infrastructure
- High-availability multi-node runtime

The architecture may expose stable interfaces for these future features, but v1 must not implement them speculatively.

---

## 4. Core Architecture

```text
                         AGENTS FACTORY
                               │
                    ┌──────────┴──────────┐
                    │    CONTROL PLANE    │
                    │      private        │
                    └──────────┬──────────┘
                               │
                         Agent Factory
                               │
                           AgentSpec
                               │
                        Agent Instance
                               │
               ┌───────────────┼────────────────┐
               │               │                │
        Customer Service    Capability       Tenant
              Core            Packs           Config
                               │
             ┌─────────────────┼──────────────────┐
             │                 │                  │
        Appointments         Orders        Returns & Claims
                               │
                               ▼
                       Integration Layer
                               │
        ┌──────────────────────┼─────────────────────┐
        │                      │                     │
 Google Workspace        WooCommerce           Custom APIs
                               │
                               ▼
                    OpenAI Agents SDK
                         Runtime
                            │
                            ▼
                    GPT-5.6 Luna
                  reasoning effort: low
```

Agents Factory owns the product contract. OpenAI Agents SDK is the initial runtime implementation and must remain replaceable behind an internal runtime boundary.

Hermes is not part of the commercial product name or runtime architecture.

---

## 5. AgentSpec

`AgentSpec` is the executable definition of an Agent Instance. It is generated from reusable platform components and tenant configuration.

Conceptually:

```text
Agent Template
+ Tenant Config
+ Brand Persona
+ Enabled Capabilities
+ Connector Bindings
+ Knowledge Version
+ Policies
+ Identity Requirements
+ Approval Routes
+ Model Configuration
= AgentSpec Version
```

An AgentSpec version must be immutable once promoted to Production. Changes create a new version.

At minimum the AgentSpec contract must identify:

- tenant
- agent product and version
- persona configuration
- active capabilities and versions
- permitted tools/actions
- connector bindings
- policy version
- identity policy
- approval routes
- knowledge version
- model and reasoning configuration
- language policy
- human-operation configuration
- runtime limits

---

## 6. Customer Service Core

Every Agent Customer Service instance inherits a centrally maintained core:

```text
Customer Service Core
├── Natural Conversation
├── Greeting Policy
├── Business Scope Guard
├── Knowledge Retrieval
├── Identity Assurance
├── Action Policy Engine
├── Customer Confirmation
├── Approval Engine
├── Case Management
├── Live Human Handoff
├── Backoffice Review
├── Reliability / Error Handling
├── Abuse & Conflict Policy
├── Language Policy
└── Audit & Observability
```

Tenant configuration may customize presentation and business rules within allowed bounds but may not disable platform safety, isolation, authorization, approval, or audit invariants.

---

## 7. Persona, Greeting, and Transparency

Tenant-configurable fields include:

- optional agent name
- tone
- formality
- primary locale
- supported language set
- brand vocabulary
- greeting
- quick options

The platform must not require a first-message statement that the agent is AI.

Permitted greeting styles include:

- Named: “Hola, soy Solia, de Empresa ABC. ¿En qué puedo ayudarte?”
- Brand-only: “¡Hola! Bienvenido a Empresa ABC. ¿En qué podemos ayudarte?”

The agent must not impersonate a specific real human employee. If directly asked whether it is human, it must truthfully identify itself as an automated or virtual assistant.

Quick options are generated from active capabilities and are orientation aids, not a rigid menu. Free natural-language input remains available at all times.

The “Hablar con una persona” option is shown only when Live Human Handoff is enabled and a valid human response surface is configured.

---

## 8. Business Scope Guard

Agent Customer Service is not a general-purpose assistant.

In scope:

- company information
- products and services
- orders
- appointments
- claims and returns
- policies
- supported business processes
- enabled capabilities

Out-of-scope requests are redirected naturally without robotic “out of scope” language.

Intent is evaluated semantically. A sentence such as “Está lloviendo, ¿puedo cambiar mi cita?” remains in scope because the operational intent is appointment rescheduling.

The agent must resist attempts to override the Business Scope Guard or system policies through prompt injection or conversational pressure.

---

## 9. Language Policy

v1 supports:

- Spanish
- English

Default locale: `es-CO`.

The agent automatically detects the customer's supported language and responds in that language. It should not switch language because of an isolated foreign word, brand name, product term, or legal term.

---

## 10. Conversation Control State vs Workflow State

To avoid ambiguity, Agents Factory separates **conversation control** from **business workflow/case state**.

### 10.1 Conversation control state

This determines who may respond to the WhatsApp conversation:

```text
AI_ACTIVE
AWAITING_HUMAN
HUMAN_ACTIVE
CLOSED
```

Rules:

- `AI_ACTIVE`: AI may respond.
- `AWAITING_HUMAN`: handoff requested and waiting for a configured human surface; AI behavior follows handoff policy and does not falsely promise an active human if none is available.
- `HUMAN_ACTIVE`: AI stores incoming events but must not respond.
- `CLOSED`: no active conversation. A new inbound message may open a new AI-active session according to policy.

### 10.2 Workflow/case state

States such as `AWAITING_INFORMATION` and `PENDING_APPROVAL` belong to an action/case workflow. They do not automatically mean the AI must stop responding.

For example, a customer may continue asking for the status of a `PENDING_APPROVAL` case while the conversation remains `AI_ACTIVE`.

This separation is a hard design rule.

---

## 11. Identity Assurance

Identity levels:

```text
LEVEL 0 — unknown
LEVEL 1 — recognized WhatsApp identity
LEVEL 2 — additional verification
LEVEL 3 — strong verification / OTP or external authentication
```

Each action declares its minimum identity level.

Example:

```text
orders.get_status                 → Level 1
orders.update_shipping_address    → Level 2
future sensitive account change  → Level 3
```

Authentication and authorization are separate concepts. Recognition of a WhatsApp number does not imply permission to execute every action.

---

## 12. Action Policy Engine

Risk levels:

```text
LOW     — read / low-consequence operation
MEDIUM  — write / consequential operation
HIGH    — sensitive or high-consequence operation
```

Default enforcement:

```text
LOW     → execute automatically when identity/authorization requirements pass
MEDIUM  → require customer confirmation
HIGH    → require customer confirmation + backoffice approval
```

A tenant may choose stricter requirements but cannot weaken Agents Factory's minimum sensitive-action protections.

Every action must be auditable and include, at minimum:

- action id
- tenant id
- conversation id
- customer reference
- capability/action type
- risk level
- identity level achieved
- normalized parameters
- confirmation evidence
- approval reference if applicable
- connector used
- execution result
- timestamps

---

## 13. Action Lifecycle and Reliability

Canonical action lifecycle:

```text
REQUESTED
→ IDENTITY_VERIFIED
→ AWAITING_CONFIRMATION
→ CONFIRMED
→ AWAITING_APPROVAL (when required)
→ EXECUTING
→ SUCCEEDED
```

Alternate outcomes:

```text
REJECTED
FAILED
UNCERTAIN
EXPIRED
HANDED_OFF
```

### 13.1 Idempotency

Every write/action uses an `action_id` or equivalent idempotency key. Retries must not create duplicate appointments, duplicate updates, duplicate cancellations, or duplicate customer messages.

### 13.2 Revalidation

Before execution, especially after delayed approval, the backend revalidates current state and preconditions.

Example: an approved cancellation request must not execute if the order has already entered a non-cancellable state.

### 13.3 Fail closed

If the system cannot determine whether a sensitive write succeeded, the action becomes `UNCERTAIN`. The agent must not tell the customer it succeeded. A safe verification or backoffice path is required.

### 13.4 Retries

Retries are limited and operation-aware. Writes are never retried blindly.

---

## 14. Capability Model

### 14.1 Capability vs Connector

A **Capability** defines what business operation the agent can perform.

A **Connector** defines which external system implements or stores that operation.

Example:

```text
Orders Capability
      ↓
orders.get_status()
      ↓
Connector Binding
├── WooCommerce
├── Google Sheets
└── future ERP
```

Business-domain tool contracts such as `orders.get_status()` are preferred over system-specific model-facing tool names.

### 14.2 Capability Pack contract

A Capability Pack is reusable and versioned. It may include:

- intents
- workflows
- business schemas
- tools
- connector contracts
- identity requirements
- customer-confirmation rules
- approval rules
- failure behavior
- handoff behavior
- evals

Only tools belonging to active/relevant capabilities should be exposed to the runtime for a given execution. Tool gating reduces unnecessary model surface area.

---

## 15. v1 Capability Packs

### 15.1 Appointments

Required operations:

```text
check_availability
create_appointment
get_appointment
reschedule_appointment
request_cancellation
```

Initial connector: **Google Calendar**.

Configuration model:

```text
Service
+ Main Professional
+ Location
+ Availability Rules
+ Booking Policies
```

v1 does not support multiple simultaneous resource constraints such as room + equipment + professional.

Availability is computed from:

- service duration and buffers
- professional working hours
- allowed location
- Google Calendar occupancy
- lead time
- booking policies

Before create/reschedule, the system revalidates availability. v1 does not implement temporary slot holds.

Default risk policy:

- check availability / get appointment: LOW
- create appointment: MEDIUM, identity Level 1, confirmation
- reschedule: MEDIUM, identity Level 2, confirmation
- cancellation request: HIGH, identity Level 2, confirmation + backoffice approval

Appointment communications:

- immediate confirmation
- one configurable reminder
- attendance confirmation
- reschedule option
- cancellation request

Proactive WhatsApp messaging must use an approved template whenever Meta policy requires template-based initiation.

### 15.2 Orders

Required read operations:

```text
find_order
get_status
get_tracking
get_items
get_delivery_information
```

Required write/request operations:

```text
update_shipping_address
update_contact_information
add_order_note
request_order_cancellation
```

Required issue flows:

```text
missing_order
wrong_product
damaged_product
delivery_delay
create_claim
```

Initial connectors:

- WooCommerce
- Google Sheets

Default risk policy:

- reads: LOW, generally identity Level 1
- contact/address updates: MEDIUM, identity Level 2 + confirmation
- cancellation request: HIGH, identity Level 2 + confirmation + approval

Connector implementations declare supported operations. Unsupported actions must not be offered as executable actions.

### 15.3 Returns & Claims

v1 scope is intentionally conservative:

```text
identify
classify
collect evidence
validate completeness/policy
create case
backoffice review
communicate status/result
```

Supported issue classes include:

- wrong product
- damaged product
- incomplete order
- not received
- late delivery
- product/service nonconformity
- return request

The capability may collect:

- description
- order/customer/item identifiers
- dates
- photos
- videos
- PDFs/documents
- requested resolution

v1 must not autonomously:

- approve a return
- refund money
- issue credit notes
- promise acceptance

For customers without a CRM/helpdesk, the standard operational destination is:

```text
Google Sheets → case queue/status
Google Drive  → evidence
Gmail         → notifications/approvals
```

---

## 16. Case Management

### 16.1 Canonical lifecycle

```text
OPEN
→ AWAITING_INFORMATION
→ READY_FOR_REVIEW
→ PENDING_APPROVAL
→ IN_PROGRESS
→ RESOLVED
→ CLOSED
```

Additional state paths:

```text
REOPENED
REJECTED
CANCELLED
EXPIRED
DUPLICATE
```

`RESOLVED` means the current issue is believed solved but remains easily reopenable. Default auto-close is **72 hours** after resolution without a customer response; this is configurable per tenant.

If the customer indicates that the issue persists during the reopen window, the same case transitions to `REOPENED` rather than creating a duplicate.

### 16.2 Deduplication

Before creating a case, the system checks for a materially equivalent open case using a key conceptually based on:

```text
tenant_id
+ customer_id
+ capability
+ case/action type
+ resource_id
```

A status question about an existing case must not create a new case.

### 16.3 Pending cases

While a case is `PENDING_APPROVAL`, the customer may keep writing. The agent should recognize the existing case and provide its current status.

Agents Factory does not send periodic “still pending” WhatsApp reminders. It sends proactive updates only on meaningful state changes or when more customer information is required.

### 16.4 Priority

Case Priority Engine levels:

```text
LOW
NORMAL
HIGH
CRITICAL
```

Priority is driven primarily by structured rules. The LLM may interpret text/context, but final priority assignment follows deterministic policy.

### 16.5 Response Targets

Default configurable operational targets:

```text
LOW      → 48 hours
NORMAL   → 24 hours
HIGH     → 4 hours
CRITICAL → 30 minutes
```

These are internal **Response Targets**, not contractual SLAs.

A case can be marked:

```text
ON_TRACK
APPROACHING_TARGET
OVERDUE
```

Approaching/overdue status creates operational alerts.

---

## 17. Human Operations

Agents Factory separates two concepts.

### 17.1 Live Human Handoff

Optional per tenant:

```text
live_human_handoff.enabled = true | false
```

A handoff can be triggered by:

- clear customer request for a human
- system-required risk/policy escalation
- repeated integration failure
- unresolved or uncertain consequential action

Ambiguous phrases such as “necesito ayuda” do not automatically trigger handoff.

When enabled:

```text
AI_ACTIVE
→ AWAITING_HUMAN
→ HUMAN_ACTIVE
```

While `HUMAN_ACTIVE`, the AI must not respond.

Default inactivity close window: **12 hours**, configurable per tenant. After close, the next customer message returns to AI service according to normal session rules.

v1 has no Agents Factory human inbox. Therefore Live Human Handoff may only be enabled when a valid response surface exists, such as:

- supported WhatsApp Coexistence using WhatsApp Business App
- a supported external CRM/helpdesk/inbox integration

API-only mode without a human response surface must not offer live handoff.

### 17.2 Backoffice Review & Approval

Backoffice review is independent from Live Human Handoff and is part of the Standard product path for consequential operations.

A small business may use its owner or manager as the responsible reviewer even when no person is chatting directly with customers.

High-risk operations require a configured responsible reviewer.

---

## 18. Backoffice Approval Flow

Canonical flow:

```text
Customer requests high-risk action
→ identity verification
→ customer confirmation
→ approval request created
→ authorized approver receives email
→ secure temporary single-use page/link
→ OTP sent to authorized approver email
→ APPROVE / REJECT
→ first valid response closes request
→ backend revalidates current state
→ execute if approved and still valid
→ agent automatically communicates result on WhatsApp
→ audit decision, execution, notification, delivery status
```

Approval Routes are configurable by Capability + Action and support one or multiple authorized email addresses.

v1 strategy: `first_response`.

The first valid approval or rejection invalidates remaining links. Expired approval requests do not execute.

The approval page records audit metadata such as approver identity, timestamp, IP/user-agent where legally/operationally appropriate, and verification result. OTP secrets themselves are never stored in logs.

Customer messages after decision are generated from a structured decision/execution result, not invented from a bare boolean.

Example internal result shape:

```yaml
decision:
  status: rejected
  reason_code: order_already_shipped
  customer_safe_explanation: "El pedido ya fue despachado."
  next_actions:
    - create_return_claim
```

---

## 19. Abuse & Conflict Policy

If the customer is rude but has a valid business request, the agent continues helping in a neutral, direct, professional manner.

It must not lecture the user, become defensive, or over-apologize.

If the customer only insults/provokes without a business request, the agent redirects once. Persistent abuse may close the conversation.

Credible threats or safety incidents require evidence preservation and incident routing according to tenant/platform policy; the agent must not argue or improvise.

Frustration by itself does not force a human handoff.

---

## 20. WhatsApp Channel Architecture

v1 is WhatsApp-first and uses **Meta WhatsApp Cloud API** directly.

Internal abstraction:

```text
WhatsAppProvider
      ↓
MetaCloudApiProvider
```

The rest of the product must depend on the internal interface rather than Meta-specific implementation details.

### 20.1 Inbound flow

```text
WhatsApp
→ Meta Cloud API
→ webhook
→ signature validation
→ tenant resolution
→ deduplication
→ persist inbound event
→ acknowledge webhook quickly
→ durable queue
→ conversation ordering/lock
→ Agent Worker
```

### 20.2 Embedded Signup

Commercial onboarding should support Meta Embedded Signup so the client authorizes its own business/number without sharing credentials manually.

### 20.3 Coexistence

Where Meta/account eligibility supports it, the same number may support:

```text
Cloud API → AI
WhatsApp Business App → human
```

Agents Factory must also support API-only mode. Coexistence cannot be assumed for every tenant.

### 20.4 Template Registry

v1 synchronizes/maps approved Meta templates rather than providing a full template editor.

Examples:

- appointment confirmation
- appointment reminder
- case created/status update
- order status update
- human follow-up

The platform validates ownership, approval status, language, required variables, send result, and cost attribution.

---

## 21. Multimodal Input

v1 inbound types:

- text
- voice notes
- images
- PDF
- location
- contacts
- video storage for human review

Response modality in v1: **text only**.

### 21.1 Media Processor boundary

GPT-5.6 Luna is not treated as the universal media processor. Media is normalized before agent reasoning when needed.

Conceptual pipeline:

```text
Voice note → speech-to-text service → text → agent
PDF        → extraction/parser → text/structured content → agent or knowledge flow
Image      → approved image-capable model/runtime path → normalized observation → agent
Location   → structured WhatsApp payload → normalized business input
Contact    → structured WhatsApp payload → normalized business input
Video      → private storage + metadata → human review (no advanced v1 analysis)
```

The specific speech-to-text component is an implementation choice and must be selected in the implementation plan based on supported API, cost, latency, and data requirements.

All media is tenant-scoped and subject to retention policy.

---

## 22. Knowledge Architecture

Agents Factory separates critical structured data from unstructured knowledge.

### 22.1 Structured business data

Examples:

- business hours
- locations
- service catalog
- prices
- contacts
- booking rules
- approval contacts

These values are queried as structured records, not through RAG by default.

### 22.2 Knowledge Base / RAG

Examples:

- policies
- manuals
- detailed FAQs
- catalog descriptions
- procedures
- documentation

v1 uses:

```text
Supabase PostgreSQL
+ pgvector
+ KnowledgeRepository abstraction
```

Retrieval is always tenant-scoped.

### 22.3 Source authority

Authority levels:

```text
AUTHORITATIVE
SECONDARY
REFERENCE
```

A lower-authority source cannot silently override a higher-authority source.

### 22.4 Provenance

Important extracted/configured values retain:

- source id
- source type
- authority
- source version
- verification timestamp
- approving user/admin

### 22.5 AI-assisted onboarding

Knowledge sources may include:

- website
- PDF
- DOCX
- Google Drive
- Google Sheets / Excel upload
- FAQ/catalog/manual upload
- manual entry

Microsoft OneDrive/SharePoint is represented in the Integration Catalog architecture but is not a release blocker for the first MVP unless required by the launch tenant.

AI proposes structured data and knowledge; it never auto-publishes extracted content to Production.

### 22.6 Change detection

Connected source changes may be detected automatically:

```text
source change
→ diff
→ proposed update
→ conflict detection
→ admin review
→ new Draft knowledge version
→ Test
→ Quality Gate
→ Production
```

No source update silently modifies Production.

---

## 23. Integration Layer

### 23.1 Initial required connector set

The initial MVP must support:

- Meta WhatsApp Cloud API
- Google Calendar
- Gmail
- Google Drive
- Google Sheets
- WooCommerce

Google Contacts may be included when required by a workflow but is not a release blocker by itself.

The generic REST API/Webhook connector foundation for Custom Onboarding is deferred to v1.1 under the approved 2026-08-14 scope amendment. v1 keeps the `Connector` abstraction and Custom Connector classification, but does not implement an executable generic REST adapter, auth flow, client, or webhook route.

The Integration Catalog may display planned Microsoft 365, HubSpot, Shopify, CRM/helpdesk, accounting, and other connectors as unavailable/coming later without implementing them.

### 23.2 Connector contract

Each connector declares supported operations/capabilities. Agent behavior must be gated by those declared capabilities.

### 23.3 OAuth

OAuth integrations are connected from the Control Plane. The client performs authorization directly with the external provider. Agents Factory requests least-privilege scopes.

### 23.4 Non-OAuth credentials

API keys and similar credentials are encrypted before storage.

The model never receives credentials or raw refresh tokens.

---

## 24. Secret Management

v1 design:

```text
Supabase → encrypted secret payload
VPS environment → master encryption key
Backend integration service → decrypt only when required
```

Requirements:

- master key is not stored in the database, frontend, repository, prompt, or logs
- token refresh happens in backend services
- connect/revoke/refresh events are audited without secret values
- secrets are redacted from traces/errors
- architecture permits future migration to managed KMS/secret-manager services

---

## 25. Data Platform and Tenant Isolation

Supabase is the v1 data platform and provides:

- PostgreSQL
- Row Level Security
- pgvector
- Storage
- authentication where used by the Control Plane

### 25.1 Standard tenant model

```text
shared runtime
+ shared PostgreSQL
+ tenant_id
+ RLS
+ tenant-scoped repositories
```

Entities requiring tenant ownership include at minimum:

- agent instances
- conversations/messages
- customers/references
- cases
- actions
- approvals
- knowledge sources/documents/chunks
- integrations
- usage/cost records
- audit records
- media metadata

### 25.2 Defense in depth

```text
Inbound account/number
→ Tenant Resolver
→ authenticated backend tenant context
→ service/repository enforcement
→ PostgreSQL RLS
```

Cross-tenant isolation tests are critical release blockers.

### 25.3 Enterprise future

Dedicated runtime, database/project, or infrastructure may be introduced as a premium enterprise option later. It is not implemented in v1.

---

## 26. Backend and Runtime Stack

Selected stack:

- **Frontend:** Next.js + TypeScript
- **Backend/API:** Python + FastAPI
- **Agent runtime:** OpenAI Agents SDK for Python
- **Model:** `gpt-5.6-luna`, reasoning effort `low`
- **Data:** Supabase PostgreSQL/RLS/pgvector/Storage
- **Runtime:** Hostinger VPS
- **Containers:** Docker Compose
- **Queue/coordination:** Redis
- **Repository:** one private Git monorepo

The backend is a **modular monolith**. API, workers, and scheduler may run as separate processes/containers from the same codebase.

Expected modules include:

- Tenants
- Agent Factory / Agent Definitions
- Runtime
- WhatsApp
- Conversations
- Capabilities
- Knowledge
- Integrations
- Policies
- Identity
- Approvals
- Handoffs
- Cases
- Usage/Costs
- Observability
- Evals
- Secrets

---

## 27. Queue and Asynchronous Processing

### 27.1 Persistence before queue

Important inbound events are persisted in Supabase before work is delegated to Redis.

Redis is not the source of truth.

### 27.2 Uses for Redis

- durable/managed job execution coordination at the application layer
- conversation locks
- rate limiting
- temporary coordination
- worker queues

The implementation plan must choose the Python worker framework compatible with the selected reliability requirements. The design does not require Celery or Dramatiq specifically.

### 27.3 Ordering

Messages for the same conversation are serialized using a key such as:

```text
tenant_id + conversation_id
```

Different conversations/tenants may run concurrently subject to limits.

### 27.4 Deduplication

Inbound WhatsApp dedupe key:

```text
tenant_id + whatsapp_message_id
```

### 27.5 Dead-Letter Queue

Repeatedly failed jobs transition to a DLQ and become inspectable in the Control Plane with audited retry/discard/resolve actions.

---

## 28. Control Plane

The Control Plane is a private responsive web application.

v1 role model: `platform_admin` only.

Canonical navigation:

```text
Dashboard
Tenants
Agents
Capabilities
Integrations
Knowledge
Conversations
Cases
Evals
Usage & Costs
Operations
Settings
```

The UI should hide implementation complexity and present business configuration through forms, toggles, mappings, health indicators, tests, and guided steps rather than requiring YAML/code edits.

---

## 29. Canonical Client Onboarding Wizard

The final canonical wizard is:

```text
1. Company
2. Agent
3. Capabilities
4. Integrations
5. Knowledge & Conflict Review
6. Policies & Identity
7. Human Operations
8. Approval Routes
9. WhatsApp
10. Test
11. Quality Gate
12. Production
```

Each step includes:

- instructions
- required fields
- validation
- current status
- test actions
- blocking errors
- warnings
- links to relevant internal documentation

Progress is resumable.

---

## 30. Client Onboarding Playbook

This playbook is the operating procedure for onboarding a tenant.

### Phase 1 — Discovery

1. Identify customer-service use cases and channels.
2. Determine expected WhatsApp volume.
3. Map business processes to existing Capability Packs.
4. Inventory current systems and data sources.
5. Determine Live Human Handoff requirement and available response surface.
6. Identify high-risk actions and responsible approvers.
7. Classify onboarding as Standard or Custom.

**Output:** onboarding scope, expected capabilities/connectors, custom-work classification, responsible contacts.

### Phase 2 — Tenant Setup

1. Create tenant.
2. Enter company/legal/industry/timezone/locale information.
3. Create Agent Instance in Draft.
4. Configure persona and greeting.
5. Configure quick options based on capabilities.

**Exit criterion:** tenant and Draft Agent Instance exist with valid base configuration.

### Phase 3 — Capabilities

1. Enable required Capability Packs.
2. Configure capability-specific catalogs and policies.
3. Confirm unsupported requested operations.
4. If missing functionality exists, classify it as Custom Connector, Custom Workflow, or New Capability.

**Exit criterion:** all promised standard operations are represented in the Draft AgentSpec.

### Phase 4 — Integrations

1. Connect Google/Meta/WooCommerce or other approved connectors.
2. Client performs OAuth/Meta authorization personally.
3. Map fields for Google Sheets or generic sources.
4. Verify declared connector operations.
5. Run connection health tests.

**Exit criterion:** every required production connector is healthy and only exposes supported operations.

### Phase 5 — Knowledge

1. Add approved sources.
2. Assign source authority.
3. Run AI extraction.
4. Review structured data proposals.
5. Review knowledge chunks/documents.
6. Resolve conflicts.
7. Approve Draft knowledge version.

**Exit criterion:** no unresolved critical conflict and every critical business value has traceable provenance.

### Phase 6 — Policies & Identity

1. Review platform defaults for each enabled action.
2. Configure stricter tenant requirements if needed.
3. Confirm identity methods available to the tenant.
4. Verify confirmation copy/flow.

**Exit criterion:** every action has explicit risk, identity, confirmation, and approval requirements.

### Phase 7 — Human Operations & Approvals

1. Enable/disable Live Human Handoff.
2. Verify Coexistence or external human response surface before enabling handoff.
3. Configure human support hours if applicable.
4. Configure Backoffice Approval Routes.
5. Add authorized approver emails.
6. Test secure link + OTP + first-response behavior.
7. Verify automatic customer notification after approval/rejection.

**Exit criterion:** no high-risk action exists without a valid approval route.

### Phase 8 — WhatsApp

1. Complete Meta Embedded Signup or approved setup.
2. Verify WABA/phone mapping to tenant.
3. Verify webhook routing and signatures.
4. Sync approved templates.
5. Test inbound/outbound messages.
6. Verify template use for proactive messaging when required.

**Exit criterion:** number is correctly tenant-resolved and message delivery is observable.

### Phase 9 — Test

Run representative scenarios covering:

- happy-path FAQ
- business-scope redirection
- Spanish/English
- order reads
- write confirmation
- high-risk approval
- approval rejection
- state change before approved execution
- case creation/deduplication/reopen
- multimodal input
- human handoff if enabled
- unavailable integration
- duplicate webhook
- retry/idempotency
- tenant-isolation attack cases

Use sandbox/simulated execution for real-world writes wherever practical.

### Phase 10 — Quality Gate

Run global + capability + tenant-specific evals.

Critical failures block Production.

### Phase 11 — Production

1. Review exact AgentSpec version.
2. Review Knowledge version.
3. Confirm WhatsApp/integration health.
4. Publish explicitly.
5. Record deployment/version metadata.
6. Monitor first production conversations and costs closely.

### Phase 12 — Post-Go-Live

1. Review conversations and cases.
2. Tag failures by category.
3. Convert meaningful failures into anonymized eval cases.
4. Monitor cost, latency, tool success, case targets, and integration health.
5. Iterate through Draft → Test → Quality Gate → Production.

---

## 31. Standard vs Custom Onboarding

### Standard Onboarding

Uses existing:

- Customer Service Core
- Capability Packs
- Connectors
- configuration
- mappings
- knowledge sources
- policies within allowed configuration

No product code modification is required.

### Custom Onboarding

Required when the customer needs functionality not covered by the standard platform.

Classifications:

1. **Custom Connector** — business capability exists, external system is new.
2. **Custom Workflow** — required business process/rules differ materially from standard workflow.
3. **New Capability** — reusable business function does not yet exist.

Customer-exclusive changes are implemented as a **Tenant Extension**, not scattered tenant-id conditionals in core code.

A Tenant Extension is versioned, documented, isolated, testable, deployable, disableable, and rollback-capable.

Reusable Tenant Extensions may later be generalized into official Capability Packs or Connectors.

---

## 32. Agent Configuration Lifecycle

Agent configuration state:

```text
DRAFT
→ TEST
→ QUALITY_GATE
→ PRODUCTION
```

Changes to the following create a new Draft version rather than altering Production directly:

- persona
- capabilities
- integration bindings
- knowledge
- policies
- identity rules
- approval routes
- runtime/model configuration

Production supports rollback to a previously valid version when compatible with current data/schema constraints.

---

## 33. Test Console

The Control Plane includes a Test Console that shows:

- simulated conversation
- active AgentSpec version
- detected intent/capability
- identity level
- tool calls
- knowledge sources
- action state
- approval state
- cost/usage
- latency
- trace events

Execution modes:

```text
Sandbox / Simulated
Real test environment
```

Test mode must avoid accidental production writes.

---

## 34. Evals and Quality Gate

Eval categories:

- conversational behavior
- business-scope compliance
- knowledge/source authority
- tool selection and result handling
- identity requirements
- authorization
- customer confirmation
- high-risk approvals
- tenant isolation
- human control state
- failure/uncertainty handling
- capability-specific workflows
- tenant-specific regressions

Critical failures that block Production include:

- cross-tenant data access
- sensitive action without required authorization/identity
- write without required confirmation
- high-risk action without approval
- secret exposure
- AI response while `HUMAN_ACTIVE`
- false success claim after uncertain consequential action

Other quality metrics may use configurable thresholds.

---

## 35. Conversation Review and Learning Loop

Control Plane review categories include:

- AI resolved
- human handoff
- tool failure
- policy violation
- complaint
- high-cost conversation
- flagged conversation

Manual labels:

- correct
- incorrect
- unsafe
- knowledge problem
- integration problem
- model reasoning problem

Learning loop:

```text
Production failure
→ review
→ anonymize/minimize
→ convert to eval
→ fix
→ Quality Gate
→ deploy
```

This creates a growing regression suite from real product experience.

---

## 36. Usage and Cost Engine

Per tenant/run/conversation, record where available:

- model
- input tokens
- cached input tokens
- reasoning tokens
- output tokens
- request count
- LLM cost
- WhatsApp cost
- external API/tool cost
- storage/infrastructure allocation
- latency

The initial model target is `gpt-5.6-luna` with `low` reasoning because v1 prioritizes economical high-volume customer-service workloads. Model selection is a measured decision: routing to additional models is not implemented until production eval/cost evidence justifies it.

Dashboards should support:

- cost per conversation
- cost per resolved case
- cost per action
- cost per tenant
- revenue vs variable cost
- estimated gross margin

---

## 37. Usage Guardrails

Per-tenant commercial/operational controls may include:

- message quota
- conversation quota
- token/cost budget
- storage quota
- concurrency limit
- tool-call limit

Suggested progressive alerts are configurable around milestones such as 70%, 85%, and 100% of budget. Reaching 100% should normally enter grace/overage behavior rather than silently shutting down service.

Independent technical hard limits prevent loops and runaway execution:

- max tool calls/run
- max retries
- max model tokens/run
- max concurrent runs
- rate limits

---

## 38. Observability and Operations

Agents Factory distinguishes:

- logs
- metrics
- traces
- audit events
- incidents

The platform should be able to reconstruct:

```text
Tenant
Conversation
Message
AgentSpec version
Knowledge version
Capability
Tool
Connector
Action
Approval
Trace
Error
Cost
Timestamp
```

Operational health includes:

- WhatsApp webhook/provider
- OpenAI API/runtime
- Supabase
- Redis/queue
- worker health
- scheduler health
- connector health

Alert examples:

- integration disconnected/requires reauthorization
- queue backlog
- worker unavailable
- high failure rate
- cost anomaly
- CRITICAL case overdue
- WhatsApp webhook failures
- knowledge sync failure
- DLQ growth

---

## 39. Deployment Architecture

Hostinger VPS containers conceptually include:

```text
Reverse Proxy / HTTPS
Next.js Control Plane
FastAPI Backend
Agent Worker
Knowledge Worker
Outbound Worker
Scheduler
Redis
```

The runtime is deployed with Docker Compose.

v1 is a single-VPS architecture and therefore does not claim high availability. Production readiness requires a documented restore path and verified backups for durable data/configuration before the first real customer goes live.

---

## 40. Environments and CI/CD

Software environments:

```text
Development
Staging
Production
```

Rules:

- no real production customer data in development/testing
- Staging uses test tenants/accounts/numbers where possible
- secrets are environment-specific
- database migrations are versioned and exercised before Production

Recommended Git flow:

```text
feature branch
→ pull request
→ automated tests
→ merge main
→ build versioned images
→ auto-deploy Staging
→ smoke verification
→ manual Production approval
→ Production
```

GitHub Actions is the selected CI/CD automation platform.

Software environment state is separate from Agent configuration state.

---

## 41. Repository Structure

One private monorepo is preferred.

Target structure:

```text
agents-factory/
├── apps/
│   ├── control-plane/       # Next.js / TypeScript
│   └── backend/             # FastAPI / Python
├── workers/
│   ├── agent-worker/
│   ├── knowledge-worker/
│   └── outbound-worker/
├── packages/
│   ├── agent-spec/
│   ├── integrations/
│   └── shared-schemas/
├── supabase/
│   ├── migrations/
│   ├── seed/
│   └── policies/
├── evals/
├── infrastructure/
├── docs/
│   └── superpowers/
│       └── specs/
├── .env.example
├── docker-compose.yml
└── README.md
```

This is a target organization, not an instruction to create every directory before implementation needs it. Python/TypeScript package boundaries should remain language-appropriate.

---

## 42. Privacy, Retention, and Data Minimization

Default configurable retention targets:

```text
Conversation content   → 90 days
Detailed traces        → 30 days
Action/audit records   → 12 months
Aggregated metrics     → longer when anonymized/minimized
```

The product must support operational paths for:

- conversation/customer data deletion
- integration revocation
- file/media removal
- anonymization/minimization of metrics
- export where required by product/legal policy

Do not unnecessarily place the following in logs/traces:

- OTP values
- credentials/tokens
- full sensitive API responses
- payment card information
- unnecessary personal data

Retention and privacy defaults must be reviewed against applicable customer contracts and law before production commercialization; this technical specification does not substitute for legal/privacy review.

---

## 43. Control Plane UX Requirements

### Dashboard

Must answer quickly:

- Are agents operating?
- Is anything broken?
- Are critical cases overdue?
- Are integrations healthy?
- What is usage/cost?

### Tenant detail

Canonical tenant tabs:

```text
Overview
Agent
Capabilities
Integrations
Knowledge
Conversations
Cases
Usage
Settings
```

### Capability Registry

Capabilities are enabled/disabled through the UI. A change creates Draft configuration and does not directly modify Production.

### Integration Health

Each connector exposes:

- status
- last health check
- supported operations
- permissions/scopes summary
- test/reconnect/revoke actions

### Knowledge Review

The UI supports:

- source authority
- AI-extracted proposals
- conflict review
- approve/edit/reject
- version diff

### Cases

The UI surfaces:

- priority
- lifecycle state
- Response Target status
- approver/reviewer status
- tenant/customer/resource references

### Operations

The UI surfaces:

- queue health
- worker health
- DLQ
- incidents
- integration issues
- deployments

Routine operation should not require SSH access to the VPS.

---

## 44. MVP End-to-End Acceptance Criteria

Agents Factory v1 is considered functionally successful when a standard SME tenant can be onboarded end-to-end without writing tenant-specific code, provided the tenant's needs are covered by standard capabilities/connectors.

Required end-to-end flow:

```text
Create tenant
→ configure Agent Customer Service
→ AI-assisted knowledge onboarding
→ enable Capability Packs
→ connect Google/WooCommerce as needed
→ connect WhatsApp
→ configure identity/policies/approvals/human operations
→ Test
→ Quality Gate
→ explicit Production publish
→ receive real WhatsApp request
→ retrieve approved knowledge
→ execute permitted tool/action
→ confirm/approve sensitive actions correctly
→ manage a case when needed
→ notify customer of result
→ observe trace/cost/result
→ review conversation
```

Additional release acceptance criteria:

1. Duplicate WhatsApp webhooks cannot create duplicate consequential actions.
2. Cross-tenant retrieval/action tests fail closed.
3. The AI cannot respond while a conversation is `HUMAN_ACTIVE`.
4. High-risk actions cannot execute without configured approval.
5. Approval execution revalidates state.
6. Uncertain writes do not produce false success messages.
7. An integration outage degrades only affected operations where practical.
8. Knowledge changes cannot silently alter Production.
9. Costs/tokens are attributable to a tenant.
10. A problematic production conversation can become an eval/regression case.

---

## 45. Implementation Decomposition

Although this is one master product design, implementation is too broad to treat as a single undifferentiated coding task. The implementation plan should decompose work into dependency-ordered milestones.

Recommended sequence:

### Milestone 1 — Platform Foundation

- monorepo/bootstrap
- environments/configuration
- Supabase schema foundation
- tenant model + RLS
- Control Plane authentication (`platform_admin`)
- FastAPI modular skeleton
- shared IDs/audit conventions

### Milestone 2 — Messaging Runtime

- Meta webhook/provider abstraction
- inbound persistence/deduplication
- Redis queue/locking
- Agent Worker
- OpenAI Agents SDK runtime adapter
- outbound text messaging
- core conversation control state

### Milestone 3 — AgentSpec + Policies

- AgentSpec/versioning
- Customer Service Core
- Business Scope Guard
- identity framework
- Action Policy Engine
- confirmation/idempotency/action lifecycle

### Milestone 4 — Knowledge

- sources/documents/chunks
- pgvector/retrieval
- structured tenant knowledge
- authority/provenance/conflicts
- AI onboarding proposals
- versioning/publish flow

### Milestone 5 — Initial Connectors and Capabilities

- Google Workspace auth/connectors
- Appointments
- WooCommerce
- Google Sheets order connector
- Orders
- Returns & Claims
- media/evidence storage

### Milestone 6 — Cases, Approvals, and Human Operations

- Case lifecycle/dedup/priority/targets
- Gmail approval notification
- secure approval page + email OTP
- revalidation/execution result
- automatic WhatsApp decision update
- live handoff state + Coexistence/external-surface gating

### Milestone 7 — Control Plane Operational UX

- onboarding wizard
- tenant/capability/integration/knowledge screens
- Test Console
- case/conversation review
- health/operations
- usage/cost dashboard

### Milestone 8 — Evals, Hardening, and Production

- automated Quality Gate
- critical security evals
- usage/cost limits
- DLQ/incident workflows
- CI/CD
- Staging/Production deployment
- backup/restore verification
- go-live runbook

Each milestone should receive implementation-level tasks, tests, and verification criteria in the writing-plans phase.

---

## 46. Documentation Set Required by the Product

The project should ultimately maintain:

1. **Master Product & Architecture Specification** — this document.
2. **Capability Pack Documentation** — contracts, actions, risk/identity/approval matrices, evals.
3. **Integration Catalog Documentation** — auth, scopes, supported operations, error semantics.
4. **Security & Privacy Documentation** — tenant isolation, secrets, data retention, incident handling.
5. **Operations Runbook** — deploy, rollback, reconnect, DLQ, restore, rotate, incident response.
6. **Client Onboarding Playbook** — included at master level here and maintained operationally as onboarding evolves.
7. **Implementation Plans** — dependency-ordered engineering plans generated after this specification is approved.

---

## 47. Final Design Decisions

The following are frozen for the v1 design unless deliberately reopened:

- Agents Factory is a proprietary platform based on Harness Engineering principles.
- AgentSpec is the internal executable configuration contract.
- OpenAI Agents SDK for Python is the single initial runtime.
- Agent Customer Service is a single general customer-service agent, not separate vertical agents.
- GPT-5.6 Luna with low reasoning is the initial model baseline.
- WhatsApp via Meta Cloud API is the first channel.
- Customer Service uses Capability Packs: Appointments, Orders, Returns & Claims.
- Capability and Connector are separate abstractions.
- Google Calendar, Google Workspace components, WooCommerce, and Google Sheets form the initial connector set.
- The generic REST API/Webhook connector foundation is deferred to v1.1 and requires separate implementation authorization.
- Supabase is the v1 data platform.
- Standard tenants use shared runtime/database with `tenant_id` + RLS.
- Hostinger VPS runs the application/runtime.
- Backend is a modular monolith using FastAPI.
- Frontend is Next.js + TypeScript.
- Redis coordinates queues/locks/rate limits; durable business state remains in Supabase.
- Live Human Handoff and Backoffice Review are separate features.
- Backoffice approval uses secure temporary single-use links + email OTP + first-response strategy.
- Approval/rejection results are automatically communicated to customers on WhatsApp.
- Pending cases do not receive periodic “still pending” reminders.
- Case priority is LOW/NORMAL/HIGH/CRITICAL with configurable Response Targets.
- Resolved cases auto-close after 72 hours by default and can reopen when the issue persists.
- Agent configuration changes flow Draft → Test → Quality Gate → Production.
- Critical tenant isolation/authorization/approval failures block Production.
- Production failures can be converted into anonymized regression evals.
- Standard onboarding must not require customer-specific code.
- Custom code is isolated in Tenant Extensions and may later be generalized.

---

## 48. Design Review Gate

**Approval status:** Approved v1 design — implementation authorized milestone by milestone.

**Original design approval:** This specification is the written representation of the approved brainstorming design.

**Scope amendment record:** The approved 2026-08-14 Generic REST API/Webhook connector amendment is retained in [the amendment section](#approved-v1-scope-amendment--2026-08-14). It defers that foundation to v1.1 and changes no other approved v1 design decision.

**Implementation authorization:** Only Phase 0 and Milestone 1 are currently authorized. Each later milestone requires separate explicit authorization after the preceding milestone review package is accepted.
