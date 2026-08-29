# AgentSpec v1

`agent_spec.schema.json` is the generated, language-neutral contract for the
immutable executable configuration of **Agent Customer Service**.

The backend Pydantic model is the source for schema generation. A compiled
version uses canonical JSON (UTF-8, sorted keys, no insignificant whitespace)
and a lowercase SHA-256 digest. Lifecycle state and deployment history are
stored outside the document, so changing an environment cannot silently change
the AgentSpec.

Production publication is intentionally fail-closed until Task 45 supplies a
passing `ProductionQualityGate` decision for the exact AgentSpec, Knowledge,
and code digests.
