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
