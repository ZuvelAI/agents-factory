# Client onboarding playbook

Agents Factory configures each client through the shared Control Plane wizard;
it does not fork code per customer.

1. **Discovery:** record customer-service use cases, channels, expected WhatsApp
   volume, process-to-capability map, source/system inventory, handoff surface,
   high-risk actions, approvers, responsible contacts and unsupported requests.
2. **Classification:** Standard uses the approved v1 connectors/capabilities.
   A requirement for a custom ERP/API is Custom and deferred to the v1.1 Custom
   Onboarding Foundation; Generic REST is unavailable in v1.
3. **Configuration:** create tenant and agent; set Spanish/English persona, scope,
   Appointments, Orders and/or Returns & Claims; connect Meta, Google Workspace,
   Google Sheets or WooCommerce as required; ingest and approve Knowledge.
4. **Controls:** configure identity levels, confirmations, HIGH approvals, human
   handoff, retention and responsible operators. Secrets stay backend-only.
5. **Test:** complete wizard tests, tenant regressions, Quality Gate, provider
   sandbox smoke, backup/restore and rollback evidence.
6. **Launch:** approve the exact Staging release manually, monitor first
   conversations/costs/incidents and perform post-go-live review.

The original PDF remains the business baseline; this living version records the
operational details learned from each anonymized onboarding.
