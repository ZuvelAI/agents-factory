# Eval Runner v0

This directory contains the deterministic local evaluation gate introduced in
Task 9A. It exercises the internal runtime contract with a seeded fake runtime;
it does not call OpenAI, persist eval runs, publish AgentSpec versions, define
release thresholds, or act as the Production Quality Gate.

Run the versioned smoke suite with:

```bash
make eval
```

Cases are strict JSONL records with schema version `1`, a stable case ID, input
turn, in-memory fixture setup, structured expectations, explicit graders, and
optional tags. Results are normalized, redacted, timestamp-independent, and
written under the ignored `evals/results/` directory. A case or grader failure
returns a non-zero exit code.

Task 16 adds deterministic v0 observations for Customer Service scope,
Spanish/English response language, and truthful automation disclosure. These
are development regressions only; v0 still cannot satisfy or replace the
exact-digest Production Quality Gate.

Task 24 adds `appointments.jsonl`: six structured probes of the same appointment
action gate used by the connector (identity, confirmation and approval). These
observations do not call a model or provider and are not production readiness
evidence by themselves.

Task 26 adds `orders.jsonl`: 17 structured probes of the Orders action gate and
issue-completeness functions used by the capability. They cover operation risk
gates, identity, unavailable bindings and the five issue types without a model,
live provider, or production Cases engine.
